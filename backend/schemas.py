from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

from models import UserRole, FuelStatus, VacationStatus


# ---------- Auth / Users ----------

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    full_name: str
    role: UserRole
    vacation_days_limit: int


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: UserRole = UserRole.courier
    vacation_days_limit: int = 20


# ---------- Fuel ----------

class FuelEntryCreate(BaseModel):
    date: date
    liters: float
    total_price: float
    license_plate: str


class FuelEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    date: date
    liters: float
    total_price: float
    license_plate: str
    receipt_photo_path: Optional[str]
    status: FuelStatus
    created_at: datetime


class FuelSummaryItem(BaseModel):
    user_id: int
    full_name: str
    total_liters: float
    total_price: float
    unpaid_price: float


# ---------- Vacation ----------

class VacationRequestCreate(BaseModel):
    date: date


class VacationDayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    date: date
    status: VacationStatus
    created_by_admin: bool


class VacationDayColor(BaseModel):
    date: date
    color: str  # "green" | "yellow" | "red"
    approved_users: list[str]
    pending_users: list[str]


# ---------- Performance ----------

class RouteCreate(BaseModel):
    name: str


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class PerformanceEntryCreate(BaseModel):
    route_id: int
    date: date
    km_driven: float = 0
    packages_delivered: int = 0
    hours_worked: float = 0
    note: Optional[str] = None
    confirmed: bool = False


class PerformanceEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    route_id: int
    date: date
    km_driven: float
    packages_delivered: int
    hours_worked: float
    note: Optional[str]
    confirmed: bool
    updated_at: datetime
    updated_by_id: Optional[int]


class PerformanceAverages(BaseModel):
    user_id: int
    full_name: str
    avg_km: float
    avg_packages: float
    avg_hours: float
    entries_count: int


# ---------- Denní checklist ----------

class DailyChecklistUpdate(BaseModel):
    car_checked: Optional[bool] = None
    refueled: Optional[bool] = None


class DailyChecklistOut(BaseModel):
    date: date
    car_checked: bool
    refueled: bool
    form_filled: bool  # dopočítáno z existence PerformanceEntry za daný den


# ---------- Notifications ----------

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    message: str
    is_read: bool
    created_at: datetime
