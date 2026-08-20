from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import Booking, BookingStatus, User, UserRole
from schemas import BookingCreateRequest, BookingOut, MessageOut
from services.allocation import (
    AllocationError,
    find_closest_slot,
)

router = APIRouter(prefix="/api/v1/bookings", tags=["bookings"])


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: BookingCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BookingOut:
    now = datetime.now(timezone.utc)
    start_at = _aware(payload.start_at)
    end_at = _aware(payload.end_at)

    if start_at <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "start_at must be in the future"},
        )
    if end_at <= start_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "end_at must be after start_at"},
        )
    if (end_at - start_at) < timedelta(minutes=30):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "Minimum booking duration is 30 minutes"},
        )
    if start_at > now + timedelta(days=7):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "Bookings must start within 7 days"},
        )

    try:
        slot = find_closest_slot(
            db,
            category=payload.vehicle_category,
            parking_level=payload.parking_level,
            start_at=start_at,
            end_at=end_at,
        )
        booking = Booking(
            user_id=user.id,
            slot_id=slot.id,
            vehicle_number=payload.vehicle_number,
            category=payload.vehicle_category,
            level=slot.level,
            lot=slot.lot_number,
            start_at=start_at,
            end_at=end_at,
            status=BookingStatus.CONFIRMED.value,
        )
        db.add(booking)
        # Future bookings reserve the timeslot only. Do not reduce "available now"
        # counters or lock the lot for walk-in today.
        db.commit()
        db.refresh(booking)
    except AllocationError as exc:
        db.rollback()
        code = status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message}) from exc

    return BookingOut(
        id=booking.id,
        vehicle_category=booking.category,
        vehicle_number=booking.vehicle_number,
        parking_level=booking.level,
        parking_lot_number=booking.lot,
        start_at=booking.start_at,
        end_at=booking.end_at,
        status=booking.status,
        user_id=booking.user_id,
    )


@router.get("/me", response_model=list[BookingOut])
def my_bookings(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[BookingOut]:
    rows = db.scalars(
        select(Booking)
        .where(Booking.user_id == user.id)
        .order_by(Booking.start_at.desc())
    ).all()
    return [
        BookingOut(
            id=b.id,
            vehicle_category=b.category,
            vehicle_number=b.vehicle_number,
            parking_level=b.level,
            parking_lot_number=b.lot,
            start_at=b.start_at,
            end_at=b.end_at,
            status=b.status,
            user_id=b.user_id,
        )
        for b in rows
    ]


@router.get("", response_model=list[BookingOut])
def list_all_bookings(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[BookingOut]:
    rows = db.scalars(select(Booking).order_by(Booking.start_at.desc())).all()
    return [
        BookingOut(
            id=b.id,
            vehicle_category=b.category,
            vehicle_number=b.vehicle_number,
            parking_level=b.level,
            parking_lot_number=b.lot,
            start_at=b.start_at,
            end_at=b.end_at,
            status=b.status,
            user_id=b.user_id,
        )
        for b in rows
    ]


@router.post("/{booking_id}/cancel", response_model=MessageOut)
def cancel_booking(
    booking_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MessageOut:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if user.role != UserRole.ADMIN.value and booking.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    if booking.status != BookingStatus.CONFIRMED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_STATUS", "message": "Booking is not cancellable"},
        )

    now = datetime.now(timezone.utc)
    if _aware(booking.start_at) <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CANCEL_WINDOW_CLOSED", "message": "Cannot cancel after start time"},
        )

    booking.status = BookingStatus.CANCELLED.value
    db.commit()
    return MessageOut(message="Booking cancelled", code="CANCELLED")
