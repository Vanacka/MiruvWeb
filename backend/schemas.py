from datetime import date, datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict

from models import UserRole, FuelStatus, VacationStatus, PerformanceFieldType, DisputeStatus


# ---------- Auth / Users ----------

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    full_name: str
    role: UserRole
    vacation_days_limit: int
    is_active: bool
    preferred_routes: list[RouteOut] = []


class RouteAssignmentUpdate(BaseModel):
    route_ids: list[int]


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    role: UserRole = UserRole.courier
    vacation_days_limit: int = 20


class UserActiveUpdate(BaseModel):
    is_active: bool


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


class PerformanceFieldCreate(BaseModel):
    label: str
    field_type: PerformanceFieldType = PerformanceFieldType.number
    required: bool = False


class PerformanceFieldUpdate(BaseModel):
    label: Optional[str] = None
    required: Optional[bool] = None
    active: Optional[bool] = None
    position: Optional[int] = None


class PerformanceFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    label: str
    field_type: PerformanceFieldType
    required: bool
    position: int
    active: bool
    core: bool


class PerformanceEntryCreate(BaseModel):
    route_id: int
    date: date
    pocet_hd: Optional[int] = None
    pocet_boxy: Optional[int] = None
    hd_psd_box: Optional[int] = None
    svoz_do_50: Optional[int] = None
    svoz_do_100: Optional[int] = None
    svoz_nad_100: Optional[int] = None
    dobirky: Optional[int] = None
    pocet_baliku: Optional[int] = None
    nedorucene: Optional[int] = None
    km: Optional[float] = None
    note: Optional[str] = None
    extra_fields: dict[str, Any] = {}
    # None = nezadáno (u ručních oprav přes plochý formulář se stav vyplnění nemění).
    # Explicitní seznam (i prázdný) = "confirmed" se dopočítá z toho, jestli je prázdný.
    skipped_fields: Optional[list[str]] = None


class PerformanceEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    route_id: int
    date: date
    pocet_hd: Optional[int]
    pocet_boxy: Optional[int]
    hd_psd_box: Optional[int]
    svoz_do_50: Optional[int]
    svoz_do_100: Optional[int]
    svoz_nad_100: Optional[int]
    dobirky: Optional[int]
    pocet_baliku: Optional[int]
    nedorucene: Optional[int]
    km: Optional[float]
    note: Optional[str]
    confirmed: bool
    extra_fields: dict[str, Any]
    skipped_fields: list[str]
    updated_at: datetime
    updated_by_id: Optional[int]
    is_weekend: bool
    is_holiday: bool
    edit_count: int
    is_late_creation: bool  # založeno (zpětně vyplněno) v jiný den, než na který záznam je
    is_late_edit: bool  # aspoň jedna úprava proběhla v jiný den, než na který záznam je


class PerformanceEntryEditOut(BaseModel):
    id: int
    edited_by_id: int
    edited_by_name: str
    edited_at: datetime
    changes: dict[str, Any]


class DisputeCreate(BaseModel):
    route_id: int
    date: date
    pocet_hd: Optional[int] = None
    pocet_boxy: Optional[int] = None
    hd_psd_box: Optional[int] = None
    svoz_do_50: Optional[int] = None
    svoz_do_100: Optional[int] = None
    svoz_nad_100: Optional[int] = None
    dobirky: Optional[int] = None
    pocet_baliku: Optional[int] = None
    nedorucene: Optional[int] = None
    km: Optional[float] = None
    note: Optional[str] = None
    confirmed: bool = False
    extra_fields: dict[str, Any] = {}
    skipped_fields: list[str] = []


class DisputeResolve(BaseModel):
    corrected_route_id: int


class PerformanceEntryDisputeOut(BaseModel):
    id: int
    route_id: int
    route_name: str
    date: date
    status: DisputeStatus
    reported_by_id: int
    reported_by_name: str
    proposed_pocet_hd: Optional[int]
    proposed_pocet_boxy: Optional[int]
    proposed_hd_psd_box: Optional[int]
    proposed_svoz_do_50: Optional[int]
    proposed_svoz_do_100: Optional[int]
    proposed_svoz_nad_100: Optional[int]
    proposed_dobirky: Optional[int]
    proposed_pocet_baliku: Optional[int]
    proposed_nedorucene: Optional[int]
    proposed_km: Optional[float]
    proposed_note: Optional[str]
    proposed_confirmed: bool
    proposed_extra_fields: dict[str, Any]
    proposed_skipped_fields: list[str]
    conflicting_entry: PerformanceEntryOut
    conflicting_entry_owner_name: str
    corrected_route_id: Optional[int]
    corrected_route_name: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]
    resolved_by_name: Optional[str]


class PerformanceAverages(BaseModel):
    user_id: int
    full_name: str
    avg_km: float
    avg_pocet_baliku: float
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
    on_vacation: bool  # dopočítáno ze schválené dovolené na daný den


# ---------- Notifications ----------

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    message: str
    is_read: bool
    created_at: datetime
