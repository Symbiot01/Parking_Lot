from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from models import Booking, BookingStatus, ParkingHistory, ParkingSlot, ParkingSpace


class AllocationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _now() -> datetime:
    return datetime.now(timezone.utc)


def vehicle_has_open_stay(db: Session, vehicle_number: str) -> bool:
    return (
        db.scalars(
            select(ParkingHistory.id).where(
                ParkingHistory.vehicle_number == vehicle_number,
                ParkingHistory.out_at.is_(None),
            )
        ).first()
        is not None
    )


def lot_has_open_stay(db: Session, lot: str) -> bool:
    return (
        db.scalars(
            select(ParkingHistory.id).where(
                ParkingHistory.lot == lot,
                ParkingHistory.out_at.is_(None),
            )
        ).first()
        is not None
    )


def _history_overlaps(db: Session, lot: str, start_at: datetime, end_at: datetime) -> bool:
    start_at = _aware(start_at)
    end_at = _aware(end_at)
    rows = db.scalars(select(ParkingHistory).where(ParkingHistory.lot == lot)).all()
    for row in rows:
        in_at = _aware(row.in_at)
        out_at = _aware(row.out_at) if row.out_at else None
        if out_at is None:
            if in_at < end_at:
                return True
        elif in_at < end_at and out_at > start_at:
            return True
    return False


def _booking_overlaps(db: Session, lot: str, start_at: datetime, end_at: datetime) -> bool:
    start_at = _aware(start_at)
    end_at = _aware(end_at)
    bookings = db.scalars(
        select(Booking).where(
            Booking.lot == lot,
            Booking.status == BookingStatus.CONFIRMED.value,
        )
    ).all()
    for booking in bookings:
        b_start = _aware(booking.start_at)
        b_end = _aware(booking.end_at)
        if b_start < end_at and b_end > start_at:
            return True
    return False


def is_slot_free_for_window(
    db: Session,
    slot: ParkingSlot,
    start_at: datetime,
    end_at: datetime,
) -> bool:
    if lot_has_open_stay(db, slot.lot_number) and _aware(start_at) <= _now() < _aware(end_at):
        # open stay blocks any window covering now; also block general overlaps below
        pass
    if lot_has_open_stay(db, slot.lot_number):
        # Any open stay means history In without Out — lot is occupied
        open_row = db.scalars(
            select(ParkingHistory).where(
                ParkingHistory.lot == slot.lot_number,
                ParkingHistory.out_at.is_(None),
            )
        ).first()
        if open_row is not None:
            in_at = _aware(open_row.in_at)
            # open stay occupies [in_at, +inf)
            if in_at < _aware(end_at):
                return False
    if _history_overlaps(db, slot.lot_number, start_at, end_at):
        return False
    if _booking_overlaps(db, slot.lot_number, start_at, end_at):
        return False
    return True


def is_slot_free_now(db: Session, slot: ParkingSlot) -> bool:
    """Walk-in availability: only block open stays and bookings covering *now*.

    A booking for tomorrow must not lock the lot for today.
    """
    now = _now()
    if lot_has_open_stay(db, slot.lot_number):
        return False
    covering = db.scalars(
        select(Booking).where(
            Booking.lot == slot.lot_number,
            Booking.status == BookingStatus.CONFIRMED.value,
            Booking.start_at <= now,
            Booking.end_at > now,
        )
    ).first()
    return covering is None


def get_levels(db: Session, parking_level: int | None) -> list[ParkingSpace]:
    if parking_level is not None:
        space = db.scalars(
            select(ParkingSpace).where(ParkingSpace.level == parking_level)
        ).first()
        if space is None:
            raise AllocationError("VALIDATION_ERROR", "Parking level does not exist")
        return [space]
    return list(db.scalars(select(ParkingSpace).order_by(ParkingSpace.level.asc())).all())


def find_closest_slot(
    db: Session,
    category: str,
    parking_level: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> ParkingSlot:
    """Earliest floor, then closest distance_from_entry."""
    levels = get_levels(db, parking_level)
    for space in levels:
        available = space.twa if category == "TW" else space.fwa
        if start_at is None and parking_level is not None and available <= 0:
            raise AllocationError("LEVEL_FULL", "No available slots on this level")

        slots = db.scalars(
            select(ParkingSlot)
            .where(
                ParkingSlot.level == space.level,
                ParkingSlot.category == category,
                ParkingSlot.is_active.is_(True),
            )
            .order_by(ParkingSlot.distance_from_entry.asc(), ParkingSlot.lot_number.asc())
        ).all()

        for slot in slots:
            if start_at is not None and end_at is not None:
                free = is_slot_free_for_window(db, slot, start_at, end_at)
            else:
                free = is_slot_free_now(db, slot)
            if free:
                return slot

        if parking_level is not None:
            raise AllocationError("LEVEL_FULL", "No available slots on this level")

    raise AllocationError("NO_SLOT", "No available parking slots")


def decrement_counter(db: Session, level: int, category: str) -> None:
    space = db.scalars(select(ParkingSpace).where(ParkingSpace.level == level)).first()
    if space is None:
        raise AllocationError("VALIDATION_ERROR", "Parking level does not exist")
    if category == "TW":
        if space.twa <= 0:
            raise AllocationError("LEVEL_FULL", "No available two-wheeler slots")
        space.twa -= 1
    else:
        if space.fwa <= 0:
            raise AllocationError("LEVEL_FULL", "No available four-wheeler slots")
        space.fwa -= 1


def increment_counter(db: Session, level: int, category: str) -> None:
    space = db.scalars(select(ParkingSpace).where(ParkingSpace.level == level)).first()
    if space is None:
        return
    if category == "TW":
        space.twa = min(space.twa + 1, space.tw_capacity)
    else:
        space.fwa = min(space.fwa + 1, space.fw_capacity)


def recompute_availability_counters(db: Session) -> None:
    from services.floor_snapshot import recompute_counters_from_snapshots

    recompute_counters_from_snapshots(db)


def get_open_history(
    db: Session, vehicle_number: str, lot: str
) -> ParkingHistory | None:
    return db.scalars(
        select(ParkingHistory)
        .options(joinedload(ParkingHistory.booking))
        .where(
            ParkingHistory.vehicle_number == vehicle_number,
            ParkingHistory.lot == lot,
            ParkingHistory.out_at.is_(None),
        )
    ).first()


def slot_status(db: Session, slot: ParkingSlot) -> tuple[str, ParkingHistory | None, Booking | None]:
    open_hist = db.scalars(
        select(ParkingHistory).where(
            ParkingHistory.lot == slot.lot_number,
            ParkingHistory.out_at.is_(None),
        )
    ).first()
    if open_hist:
        return "OCCUPIED", open_hist, None

    now = _now()
    covering = db.scalars(
        select(Booking)
        .where(
            Booking.lot == slot.lot_number,
            Booking.status == BookingStatus.CONFIRMED.value,
            Booking.start_at <= now,
            Booking.end_at > now,
        )
        .order_by(Booking.start_at.asc())
    ).first()
    if covering:
        return "BOOKED", None, covering

    upcoming = db.scalars(
        select(Booking)
        .where(
            Booking.lot == slot.lot_number,
            Booking.status == BookingStatus.CONFIRMED.value,
            Booking.start_at > now,
            Booking.end_at > now,
        )
        .order_by(Booking.start_at.asc())
    ).first()
    if upcoming:
        # Reserved for a future timeslot — still free for walk-in today
        return "RESERVED", None, upcoming
    return "FREE", None, None
