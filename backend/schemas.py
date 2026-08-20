import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

VehicleCategory = Literal["TW", "FW"]


def normalize_vehicle_number(value: str) -> str:
    normalized = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9-]{4,15}", normalized):
        raise ValueError("Vehicle number must be 4-15 chars of A-Z, 0-9, or -")
    return normalized


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str
    email: EmailStr
    role: str


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str

    model_config = {"from_attributes": True}


class AvailabilityLevelAdmin(BaseModel):
    level: int
    two_wheeler_available: int
    four_wheeler_available: int


class AvailabilityLevelPublic(BaseModel):
    level: int
    two_wheeler_available: bool
    four_wheeler_available: bool


class AvailabilityResponseAdmin(BaseModel):
    levels: list[AvailabilityLevelAdmin]


class AvailabilityResponsePublic(BaseModel):
    levels: list[AvailabilityLevelPublic]


class SlotSpaceOut(BaseModel):
    level: int
    category: str
    lot_number: str
    distance_from_entry: int
    status: Literal["FREE", "OCCUPIED", "BOOKED", "RESERVED"]
    vehicle_number: str | None = None
    user_id: str | None = None
    in_at: datetime | None = None


class LockRequest(BaseModel):
    vehicle_category: VehicleCategory
    vehicle_number: str
    parking_level: int | None = None

    @field_validator("vehicle_number")
    @classmethod
    def validate_vehicle(cls, value: str) -> str:
        return normalize_vehicle_number(value)


class LockResponse(BaseModel):
    vehicle_category: str
    vehicle_number: str
    parking_level: int
    parking_lot_number: str
    locking_time: datetime
    user_id: str


class UnlockRequest(BaseModel):
    vehicle_number: str
    lot: str

    @field_validator("vehicle_number")
    @classmethod
    def validate_vehicle(cls, value: str) -> str:
        return normalize_vehicle_number(value)

    @field_validator("lot")
    @classmethod
    def validate_lot(cls, value: str) -> str:
        return value.strip().upper()


class UnlockResponse(BaseModel):
    vehicle_number: str
    parking_lot_number: str
    locking_time: datetime
    unlocking_time: datetime
    parking_fees: Decimal
    user_id: str


class BookingCreateRequest(BaseModel):
    vehicle_category: VehicleCategory
    vehicle_number: str
    parking_level: int | None = None
    start_at: datetime
    end_at: datetime

    @field_validator("vehicle_number")
    @classmethod
    def validate_vehicle(cls, value: str) -> str:
        return normalize_vehicle_number(value)


class BookingOut(BaseModel):
    id: str
    vehicle_category: str
    vehicle_number: str
    parking_level: int
    parking_lot_number: str | None = None
    start_at: datetime
    end_at: datetime
    status: str
    user_id: str

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    message: str
    code: str | None = None
