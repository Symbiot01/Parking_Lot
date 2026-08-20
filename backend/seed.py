from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import hash_password
from config import get_settings
from models import FeePolicy, ParkingSlot, ParkingSpace, User, UserRole

settings = get_settings()


def seed_all(db: Session) -> None:
    _seed_admin(db)
    _seed_fee_policies(db)
    _seed_parking(db)
    db.commit()


def _seed_admin(db: Session) -> None:
    existing = db.scalars(select(User).where(User.email == settings.admin_email.lower())).first()
    if existing:
        return
    db.add(
        User(
            name=settings.admin_name,
            email=settings.admin_email.lower(),
            password_hash=hash_password(settings.admin_password),
            role=UserRole.ADMIN.value,
        )
    )


def _seed_fee_policies(db: Session) -> None:
    for category, rate, late in (
        ("TW", settings.tw_hourly_rate, settings.tw_late_hourly_rate),
        ("FW", settings.fw_hourly_rate, settings.fw_late_hourly_rate),
    ):
        exists = db.scalars(select(FeePolicy).where(FeePolicy.category == category)).first()
        if exists:
            continue
        db.add(
            FeePolicy(
                category=category,
                hourly_rate=Decimal(rate),
                late_hourly_rate=Decimal(late),
                currency="INR",
            )
        )


def _seed_parking(db: Session) -> None:
    existing = db.scalars(select(ParkingSpace)).first()
    if existing:
        return

    for level in range(1, settings.parking_level_count + 1):
        space = ParkingSpace(
            level=level,
            twa=settings.tw_slots_per_level,
            fwa=settings.fw_slots_per_level,
            tw_capacity=settings.tw_slots_per_level,
            fw_capacity=settings.fw_slots_per_level,
        )
        db.add(space)
        db.flush()

        for seq in range(1, settings.tw_slots_per_level + 1):
            db.add(
                ParkingSlot(
                    parking_space_id=space.id,
                    level=level,
                    category="TW",
                    lot_number=f"{level}-TW-{seq:03d}",
                    distance_from_entry=seq,
                    is_active=True,
                )
            )
        for seq in range(1, settings.fw_slots_per_level + 1):
            db.add(
                ParkingSlot(
                    parking_space_id=space.id,
                    level=level,
                    category="FW",
                    lot_number=f"{level}-FW-{seq:03d}",
                    distance_from_entry=seq,
                    is_active=True,
                )
            )


if __name__ == "__main__":
    from database import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        seed_all(session)
        print("Seed completed.")
    finally:
        session.close()
