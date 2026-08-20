"""In-memory floor snapshot rebuilt from DB each mutation (DB remains source of truth)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Booking, BookingStatus, ParkingHistory, ParkingSlot, ParkingSpace


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return _aware(a_start) < _aware(b_end) and _aware(a_end) > _aware(b_start)


@dataclass
class SlotView:
    id: str
    lot_number: str
    distance_from_entry: int


@dataclass
class SoftBookingView:
    id: str
    start_at: datetime
    end_at: datetime
    vehicle_number: str

    @property
    def duration_seconds(self) -> float:
        return (_aware(self.end_at) - _aware(self.start_at)).total_seconds()


@dataclass
class FloorSnapshot:
    """Per-request working set for one level + category."""

    level: int
    category: str
    capacity: int
    space_id: str
    slots_back_first: list[SlotView]
    occupied_lots: set[str]
    hard_assigned_lots: dict[str, str]  # lot -> booking_id
    soft_bookings: list[SoftBookingView] = field(default_factory=list)

    @property
    def occupied_count(self) -> int:
        return len(self.occupied_lots)

    @property
    def soft_count(self) -> int:
        return len(self.soft_bookings)

    @property
    def hard_count(self) -> int:
        # Don't double-count lots that already have an open stay
        return len([lot for lot in self.hard_assigned_lots if lot not in self.occupied_lots])

    @property
    def unreserved_quota(self) -> int:
        """Preferred walk-in pool size (capacity not held by soft/hard/open stays)."""
        return max(0, self.capacity - self.occupied_count - self.soft_count - self.hard_count)

    def free_physical_back_first(self) -> list[SlotView]:
        blocked = self.occupied_lots | set(self.hard_assigned_lots.keys())
        return [s for s in self.slots_back_first if s.lot_number not in blocked]

    def concurrent_for_window(self, start_at: datetime, end_at: datetime, db: Session) -> int:
        """How many capacity units this floor uses during [start, end)."""
        count = 0
        for soft in self.soft_bookings:
            if _overlaps(soft.start_at, soft.end_at, start_at, end_at):
                count += 1
        for lot, booking_id in self.hard_assigned_lots.items():
            booking = db.get(Booking, booking_id)
            if booking and _overlaps(booking.start_at, booking.end_at, start_at, end_at):
                count += 1
        # Open stays consume capacity for any window that intersects [in, +inf)
        for lot in self.occupied_lots:
            hist = db.scalars(
                select(ParkingHistory).where(
                    ParkingHistory.lot == lot,
                    ParkingHistory.out_at.is_(None),
                )
            ).first()
            if hist and _aware(hist.in_at) < _aware(end_at):
                count += 1
        return count

    def can_soft_reserve(self, start_at: datetime, end_at: datetime, db: Session) -> bool:
        return self.concurrent_for_window(start_at, end_at, db) < self.capacity

    def pick_slot_back_fill(self, allow_steal_soft: bool) -> tuple[SlotView | None, SoftBookingView | None]:
        """
        Prefer unreserved physical capacity from the back.
        If quota exhausted, optionally steal soft reserve with farthest start_at.
        Returns (slot, displaced_soft_or_none).
        """
        free = self.free_physical_back_first()
        if not free:
            return None, None

        if self.unreserved_quota > 0:
            return free[0], None

        if not allow_steal_soft or not self.soft_bookings:
            return None, None

        # Soft bookings already sorted: start_at DESC, duration DESC
        displaced = self.soft_bookings[0]
        return free[0], displaced


def load_floor_snapshot(db: Session, level: int, category: str) -> FloorSnapshot | None:
    space = db.scalars(select(ParkingSpace).where(ParkingSpace.level == level)).first()
    if space is None:
        return None

    capacity = space.tw_capacity if category == "TW" else space.fw_capacity
    now = _now()

    slots = db.scalars(
        select(ParkingSlot)
        .where(
            ParkingSlot.level == level,
            ParkingSlot.category == category,
            ParkingSlot.is_active.is_(True),
        )
        .order_by(ParkingSlot.distance_from_entry.desc(), ParkingSlot.lot_number.desc())
    ).all()

    slot_views = [
        SlotView(id=s.id, lot_number=s.lot_number, distance_from_entry=s.distance_from_entry)
        for s in slots
    ]

    occupied: set[str] = set()
    open_rows = db.scalars(
        select(ParkingHistory).where(
            ParkingHistory.level == level,
            ParkingHistory.type == category,
            ParkingHistory.out_at.is_(None),
        )
    ).all()
    for row in open_rows:
        occupied.add(row.lot)

    hard: dict[str, str] = {}
    hard_bookings = db.scalars(
        select(Booking).where(
            Booking.level == level,
            Booking.category == category,
            Booking.status == BookingStatus.CONFIRMED.value,
            Booking.lot.is_not(None),
            Booking.end_at > now,
        )
    ).all()
    for b in hard_bookings:
        if b.lot:
            hard[b.lot] = b.id

    soft_rows = db.scalars(
        select(Booking).where(
            Booking.level == level,
            Booking.category == category,
            Booking.status == BookingStatus.CONFIRMED.value,
            Booking.lot.is_(None),
            Booking.end_at > now,
        )
    ).all()
    soft = [
        SoftBookingView(
            id=b.id,
            start_at=b.start_at,
            end_at=b.end_at,
            vehicle_number=b.vehicle_number,
        )
        for b in soft_rows
    ]
    soft.sort(key=lambda b: (_aware(b.start_at), b.duration_seconds), reverse=True)

    return FloorSnapshot(
        level=level,
        category=category,
        capacity=capacity,
        space_id=space.id,
        slots_back_first=slot_views,
        occupied_lots=occupied,
        hard_assigned_lots=hard,
        soft_bookings=soft,
    )


def choose_level_for_soft_booking(
    db: Session,
    category: str,
    start_at: datetime,
    end_at: datetime,
    pinned_level: int | None,
) -> FloorSnapshot:
    from services.allocation import AllocationError

    if pinned_level is not None:
        snap = load_floor_snapshot(db, pinned_level, category)
        if snap is None:
            raise AllocationError("VALIDATION_ERROR", "Parking level does not exist")
        if not snap.can_soft_reserve(start_at, end_at, db):
            raise AllocationError("LEVEL_FULL", "No capacity on this level for that timeslot")
        return snap

    spaces = db.scalars(select(ParkingSpace).order_by(ParkingSpace.level.asc())).all()
    for space in spaces:
        snap = load_floor_snapshot(db, space.level, category)
        if snap and snap.can_soft_reserve(start_at, end_at, db):
            return snap
    raise AllocationError("NO_SLOT", "No capacity available for that timeslot")


def recompute_counters_from_snapshots(db: Session) -> None:
    """Set twa/fwa = unreserved_quota per floor (walk-in preferred availability)."""
    spaces = db.scalars(select(ParkingSpace)).all()
    for space in spaces:
        for category, attr in (("TW", "twa"), ("FW", "fwa")):
            snap = load_floor_snapshot(db, space.level, category)
            if snap:
                setattr(space, attr, snap.unreserved_quota)
