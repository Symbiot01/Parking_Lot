from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import BookingStatus, ParkingSlot, ParkingSpace, ParkingHistory, User, UserRole
from schemas import (
    AvailabilityLevelAdmin,
    AvailabilityLevelPublic,
    AvailabilityResponseAdmin,
    AvailabilityResponsePublic,
    LockRequest,
    LockResponse,
    SlotSpaceOut,
    UnlockRequest,
    UnlockResponse,
)
from services.allocation import (
    AllocationError,
    decrement_counter,
    find_closest_slot,
    get_open_history,
    increment_counter,
    slot_status,
    vehicle_has_open_stay,
)
from services.billing import calculate_fee

router = APIRouter(prefix="/api/v1/parking", tags=["parking"])


@router.get("/availability")
def availability(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Any:
    spaces = db.scalars(select(ParkingSpace).order_by(ParkingSpace.level.asc())).all()
    if user.role == UserRole.ADMIN.value:
        return AvailabilityResponseAdmin(
            levels=[
                AvailabilityLevelAdmin(
                    level=s.level,
                    two_wheeler_available=s.twa,
                    four_wheeler_available=s.fwa,
                )
                for s in spaces
            ]
        )
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
    if vehicle_has_open_stay(db, payload.vehicle_number):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "VEHICLE_ALREADY_PARKED", "message": "Vehicle already parked"},
        )
    try:
        slot = find_closest_slot(
            db,
            category=payload.vehicle_category,
            parking_level=payload.parking_level,
        )
        now = datetime.now(timezone.utc)
        history = ParkingHistory(
            level=slot.level,
            type=payload.vehicle_category,
            vehicle_number=payload.vehicle_number,
            lot=slot.lot_number,
            in_at=now,
            out_at=None,
            fee=None,
            user_id=admin.id,
            booking_id=None,
        )
        db.add(history)
        decrement_counter(db, slot.level, payload.vehicle_category)
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
        parking_level=slot.level,
        parking_lot_number=slot.lot_number,
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
    increment_counter(db, history.level, history.type)
    db.commit()

    return UnlockResponse(
        vehicle_number=history.vehicle_number,
        parking_lot_number=history.lot,
        locking_time=history.in_at,
        unlocking_time=now,
        parking_fees=fee,
        user_id=history.user_id,
    )
