import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    PUBLIC = "PUBLIC"


class VehicleType(str, enum.Enum):
    TW = "TW"
    FW = "FW"


class BookingStatus(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    CONSUMED = "CONSUMED"
    NO_SHOW = "NO_SHOW"


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=UserRole.PUBLIC.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    histories: Mapped[list["ParkingHistory"]] = relationship(back_populates="user")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="user")


class ParkingSpace(Base):
    __tablename__ = "parking_spaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    level: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    twa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fwa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tw_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    fw_capacity: Mapped[int] = mapped_column(Integer, nullable=False)

    slots: Mapped[list["ParkingSlot"]] = relationship(back_populates="parking_space")


class ParkingSlot(Base):
    __tablename__ = "parking_slots"
    __table_args__ = (
        UniqueConstraint("level", "category", "distance_from_entry", name="uq_slot_distance"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    parking_space_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("parking_spaces.id"), nullable=False, index=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    lot_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    distance_from_entry: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    parking_space: Mapped["ParkingSpace"] = relationship(back_populates="slots")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="slot")


class ParkingHistory(Base):
    __tablename__ = "parking_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(2), nullable=False)
    vehicle_number: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    lot: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    booking_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("bookings.id"), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="histories")
    booking: Mapped["Booking | None"] = relationship(back_populates="histories")


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    slot_id: Mapped[str] = mapped_column(String(36), ForeignKey("parking_slots.id"), nullable=False)
    vehicle_number: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(2), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    lot: Mapped[str] = mapped_column(String(32), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BookingStatus.CONFIRMED.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="bookings")
    slot: Mapped["ParkingSlot"] = relationship(back_populates="bookings")
    histories: Mapped[list["ParkingHistory"]] = relationship(back_populates="booking")


class FeePolicy(Base):
    __tablename__ = "fee_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    late_hourly_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
