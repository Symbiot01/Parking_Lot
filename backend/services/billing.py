from datetime import datetime, timezone
from decimal import Decimal, ROUND_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import FeePolicy, ParkingHistory


def hours_billed(delta_seconds: float) -> int:
    if delta_seconds <= 0:
        return 1
    hours = Decimal(str(delta_seconds)) / Decimal("3600")
    return int(hours.to_integral_value(rounding=ROUND_UP)) or 1


def get_fee_policy(db: Session, category: str) -> FeePolicy:
    policy = db.scalars(
        select(FeePolicy)
        .where(FeePolicy.category == category)
        .order_by(FeePolicy.effective_from.desc())
    ).first()
    if policy is None:
        raise ValueError(f"No fee policy for category {category}")
    return policy


def calculate_fee(
    db: Session,
    history: ParkingHistory,
    out_at: datetime,
) -> Decimal:
    policy = get_fee_policy(db, history.type)
    rate = Decimal(policy.hourly_rate)
    late_rate = Decimal(policy.late_hourly_rate)

    if history.booking_id and history.booking is not None:
        booking = history.booking
        base_seconds = (booking.end_at - booking.start_at).total_seconds()
        fee = Decimal(hours_billed(base_seconds)) * rate
        booking_end = booking.end_at
        if booking_end.tzinfo is None:
            booking_end = booking_end.replace(tzinfo=timezone.utc)
        out_aware = out_at if out_at.tzinfo else out_at.replace(tzinfo=timezone.utc)
        if out_aware > booking_end:
            overtime = (out_aware - booking_end).total_seconds()
            fee += Decimal(hours_billed(overtime)) * late_rate
    else:
        in_at = history.in_at
        if in_at.tzinfo is None:
            in_at = in_at.replace(tzinfo=timezone.utc)
        out_aware = out_at if out_at.tzinfo else out_at.replace(tzinfo=timezone.utc)
        duration = (out_aware - in_at).total_seconds()
        fee = Decimal(hours_billed(duration)) * rate

    return fee.quantize(Decimal("0.01"))
