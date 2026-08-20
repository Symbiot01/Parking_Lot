from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import Booking, BookingStatus, ParkingHistory, ParkingSlot, ParkingSpace, User, UserRole
from schemas import (
    AvailabilityLevelAdmin,
    AvailabilityLevelPublic,
    AvailabilityResponseAdmin,
    AvailabilityResponsePublic,
    LockRequest,
    LockResponse,
    SlotSpaceOut,
    SoftBookingAdminOut,
    UnlockRequest,
    UnlockResponse,
)
from services.allocation import (
    AllocationError,
    get_open_history,
    slot_status,
    vehicle_has_open_stay,
)
from services.billing import calculate_fee
from services.floor_snapshot import (
    load_floor_snapshot,
    recompute_counters_from_snapshots,
    soft_reservation_summary,
)

router = APIRouter(prefix="/api/v1/parking", tags=["parking"])


@router.get("/availability")
def availability(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Any:
    # Always recompute so admin sees live walk-in quota (not stale zeros)
    recompute_counters_from_snapshots(db)
    db.commit()

    spaces = db.scalars(select(ParkingSpace).order_by(ParkingSpace.level.asc())).all()
    if user.role == UserRole.ADMIN.value:
        summary = {row["level"]: row for row in soft_reservation_summary(db)}
        levels = []
        for s in spaces:
            row = summary.get(s.level, {})
            levels.append(
                AvailabilityLevelAdmin(
                    level=s.level,
                    two_wheeler_available=row.get("tw_available_walkin", s.twa),
                    four_wheeler_available=row.get("fw_available_walkin", s.fwa),
                    two_wheeler_soft_reserved=row.get("tw_soft_total", 0),
                    four_wheeler_soft_reserved=row.get("fw_soft_total", 0),
                    two_wheeler_soft_active_now=row.get("tw_soft_active_now", 0),
                    four_wheeler_soft_active_now=row.get("fw_soft_active_now", 0),
                )
            )
        return AvailabilityResponseAdmin(levels=levels)
    return AvailabilityResponsePublic(
        levels=[
            AvailabilityLevelPublic(
                level=s.level,
                two_wheeler_available=s.twa > 0,
                four_wheeler_available=s.fwa > 0,
            )
            for s in spaces
        ]
    )


@router.get("/soft-reservations", response_model=list[SoftBookingAdminOut])
def list_soft_reservations(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[SoftBookingAdminOut]:
    """Soft capacity bookings (no lot yet) — shown in admin reserved list."""
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(Booking)
        .where(
            Booking.status == BookingStatus.CONFIRMED.value,
            Booking.lot.is_(None),
            Booking.end_at > now,
        )
        .order_by(Booking.level.asc(), Booking.start_at.asc())
    ).all()
    out: list[SoftBookingAdminOut] = []
    for b in rows:
        start = b.start_at if b.start_at.tzinfo else b.start_at.replace(tzinfo=timezone.utc)
        end = b.end_at if b.end_at.tzinfo else b.end_at.replace(tzinfo=timezone.utc)
        out.append(
            SoftBookingAdminOut(
                id=b.id,
                level=b.level,
                category=b.category,
                vehicle_number=b.vehicle_number,
                start_at=b.start_at,
                end_at=b.end_at,
                status=b.status,
                user_id=b.user_id,
                active_now=start <= now < end,
            )
        )
    return out


@router.get("/spaces", response_model=list[SlotSpaceOut])
def list_spaces(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[SlotSpaceOut]:
    slots = db.scalars(
        select(ParkingSlot)
        .where(ParkingSlot.is_active.is_(True))
        .order_by(
            ParkingSlot.level.asc(),
            ParkingSlot.category.asc(),
            ParkingSlot.distance_from_entry.asc(),
        )
    ).all()
    result: list[SlotSpaceOut] = []
    for slot in slots:
        status_val, hist, booking = slot_status(db, slot)
        vehicle = None
        user_id = None
        in_at = None
        if hist:
            vehicle = hist.vehicle_number
            user_id = hist.user_id
            in_at = hist.in_at
        elif booking:
            vehicle = booking.vehicle_number
            user_id = booking.user_id
        result.append(
            SlotSpaceOut(
                level=slot.level,
                category=slot.category,
                lot_number=slot.lot_number,
                distance_from_entry=slot.distance_from_entry,
                status=status_val,  # type: ignore[arg-type]
                vehicle_number=vehicle,
                user_id=user_id,
                in_at=in_at,
            )
        )
    return result


@router.post("/lock", response_model=LockResponse)
def lock_space(
    payload: LockRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> LockResponse:
    """Walk-in: fill from the back; unreserved quota first; else displace farthest soft booking."""
    if vehicle_has_open_stay(db, payload.vehicle_number):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "VEHICLE_ALREADY_PARKED", "message": "Vehicle already parked"},
        )

    try:
        levels: list[int]
        if payload.parking_level is not None:
            levels = [payload.parking_level]
        else:
            levels = [
                s.level
                for s in db.scalars(select(ParkingSpace).order_by(ParkingSpace.level.asc())).all()
            ]

        chosen_slot = None
        chosen_level = None
        displaced_id = None

        for level in levels:
            snap = load_floor_snapshot(db, level, payload.vehicle_category)
            if snap is None:
                if payload.parking_level is not None:
                    raise AllocationError("VALIDATION_ERROR", "Parking level does not exist")
                continue

            slot_view, displaced = snap.pick_slot_back_fill(allow_steal_soft=True)
            if slot_view is None:
                if payload.parking_level is not None:
                    raise AllocationError("LEVEL_FULL", "No available slots on this level")
                continue

            chosen_slot = slot_view
            chosen_level = level
            if displaced is not None:
                displaced_id = displaced.id
            break

        if chosen_slot is None or chosen_level is None:
            raise AllocationError("NO_SLOT", "No available parking slots")

        if displaced_id is not None:
            soft = db.get(Booking, displaced_id)
            if soft and soft.status == BookingStatus.CONFIRMED.value and soft.lot is None:
                soft.status = BookingStatus.DISPLACED.value

        now = datetime.now(timezone.utc)
        history = ParkingHistory(
            level=chosen_level,
            type=payload.vehicle_category,
            vehicle_number=payload.vehicle_number,
            lot=chosen_slot.lot_number,
            in_at=now,
            out_at=None,
            fee=None,
            user_id=admin.id,
            booking_id=None,
        )
        db.add(history)
        recompute_counters_from_snapshots(db)
        db.commit()
        db.refresh(history)
    except AllocationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    return LockResponse(
        vehicle_category=payload.vehicle_category,
        vehicle_number=payload.vehicle_number,
        parking_level=chosen_level,
        parking_lot_number=chosen_slot.lot_number,
        locking_time=history.in_at,
        user_id=admin.id,
    )


@router.post("/unlock", response_model=UnlockResponse)
def unlock_space(
    payload: UnlockRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UnlockResponse:
    history = get_open_history(db, payload.vehicle_number, payload.lot)
    if history is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if user.role != UserRole.ADMIN.value and history.user_id != user.id:
        if history.booking is None or history.booking.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    now = datetime.now(timezone.utc)
    fee = calculate_fee(db, history, now)
    history.out_at = now
    history.fee = fee
    if history.booking_id and history.booking is not None:
        history.booking.status = BookingStatus.CONSUMED.value
    recompute_counters_from_snapshots(db)
    db.commit()

    return UnlockResponse(
        vehicle_number=history.vehicle_number,
        parking_lot_number=history.lot,
        locking_time=history.in_at,
        unlocking_time=now,
        parking_fees=fee,
        user_id=history.user_id,
    )
