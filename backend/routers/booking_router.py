from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import get_current_user, require_admin
from database import get_db
from models import Booking, BookingStatus, ParkingHistory, User, UserRole
from schemas import BookingCreateRequest, BookingOut, MessageOut
from services.allocation import AllocationError
from services.floor_snapshot import (
    choose_level_for_soft_booking,
    load_floor_snapshot,
    recompute_counters_from_snapshots,
)

router = APIRouter(prefix="/api/v1/bookings", tags=["bookings"])


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _booking_out(b: Booking) -> BookingOut:
    return BookingOut(
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


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: BookingCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BookingOut:
    """Soft-reserve capacity: no lot assigned until check-in."""
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
        snap = choose_level_for_soft_booking(
            db,
            category=payload.vehicle_category,
            start_at=start_at,
            end_at=end_at,
            pinned_level=payload.parking_level,
        )
        booking = Booking(
            user_id=user.id,
            slot_id=None,
            vehicle_number=payload.vehicle_number,
            category=payload.vehicle_category,
            level=snap.level,
            lot=None,
            start_at=start_at,
            end_at=end_at,
            status=BookingStatus.CONFIRMED.value,
        )
        db.add(booking)
        db.flush()
        recompute_counters_from_snapshots(db)
        db.commit()
        db.refresh(booking)
    except AllocationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    return _booking_out(booking)


@router.post("/{booking_id}/check-in", response_model=BookingOut)
def check_in(
    booking_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> BookingOut:
    """Assign a physical lot at visit time (back-fill among free slots)."""
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if user.role != UserRole.ADMIN.value and booking.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    if booking.status != BookingStatus.CONFIRMED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_STATUS", "message": "Booking is not check-in eligible"},
        )
    if booking.lot is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_ASSIGNED", "message": "Lot already assigned"},
        )

    now = datetime.now(timezone.utc)
    start_at = _aware(booking.start_at)
    end_at = _aware(booking.end_at)
    grace = timedelta(minutes=15)
    if now < start_at - grace or now >= end_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "OUTSIDE_WINDOW",
                "message": "Check-in only within 15 minutes before start until end",
            },
        )

    try:
        snap = load_floor_snapshot(db, booking.level, booking.category)
        if snap is None:
            raise AllocationError("VALIDATION_ERROR", "Parking level does not exist")

        # This booking is still in soft list; converting soft → hard.
        # Temporarily ignore itself for quota by picking any free physical from the back.
        free = snap.free_physical_back_first()
        if not free:
            raise AllocationError("NO_SLOT", "No free physical slot for check-in")

        slot = free[0]
        booking.lot = slot.lot_number
        booking.slot_id = slot.id

        history = ParkingHistory(
            level=booking.level,
            type=booking.category,
            vehicle_number=booking.vehicle_number,
            lot=slot.lot_number,
            in_at=now,
            out_at=None,
            fee=None,
            user_id=booking.user_id,
            booking_id=booking.id,
        )
        db.add(history)
        recompute_counters_from_snapshots(db)
        db.commit()
        db.refresh(booking)
    except AllocationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    return _booking_out(booking)


@router.get("/me", response_model=list[BookingOut])
def my_bookings(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[BookingOut]:
    rows = db.scalars(
        select(Booking).where(Booking.user_id == user.id).order_by(Booking.start_at.desc())
    ).all()
    return [_booking_out(b) for b in rows]


@router.get("", response_model=list[BookingOut])
def list_all_bookings(
    _: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[BookingOut]:
    rows = db.scalars(select(Booking).order_by(Booking.start_at.desc())).all()
    return [_booking_out(b) for b in rows]


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

    if booking.status not in (BookingStatus.CONFIRMED.value, BookingStatus.DISPLACED.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_STATUS", "message": "Booking is not cancellable"},
        )

    if booking.lot is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_CHECKED_IN", "message": "Use unlock after check-in"},
        )

    now = datetime.now(timezone.utc)
    if _aware(booking.start_at) <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CANCEL_WINDOW_CLOSED", "message": "Cannot cancel after start time"},
        )

    booking.status = BookingStatus.CANCELLED.value
    recompute_counters_from_snapshots(db)
    db.commit()
    return MessageOut(message="Booking cancelled", code="CANCELLED")
