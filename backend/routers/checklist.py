from datetime import date as date_type

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import User, DailyChecklist, PerformanceEntry, VacationDay, VacationStatus
from schemas import DailyChecklistOut, DailyChecklistUpdate

router = APIRouter(prefix="/checklist", tags=["checklist"])


def _get_or_create_today(db: Session, user_id: int, today: date_type) -> DailyChecklist:
    item = db.query(DailyChecklist).filter(
        DailyChecklist.user_id == user_id, DailyChecklist.date == today,
    ).first()
    if not item:
        item = DailyChecklist(user_id=user_id, date=today)
        db.add(item)
        db.commit()
        db.refresh(item)
    return item


def _form_filled(db: Session, user_id: int, today: date_type) -> bool:
    return db.query(PerformanceEntry).filter(
        PerformanceEntry.user_id == user_id, PerformanceEntry.date == today,
    ).first() is not None


def _is_on_vacation(db: Session, user_id: int, day: date_type) -> bool:
    return db.query(VacationDay).filter(
        VacationDay.user_id == user_id, VacationDay.date == day,
        VacationDay.status == VacationStatus.approved,
    ).first() is not None


def _to_out(item: DailyChecklist, form_filled: bool, on_vacation: bool) -> DailyChecklistOut:
    return DailyChecklistOut(
        date=item.date, car_checked=item.car_checked, refueled=item.refueled,
        form_filled=form_filled, on_vacation=on_vacation,
    )


@router.get("/today", response_model=DailyChecklistOut)
def get_today(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    today = date_type.today()
    item = _get_or_create_today(db, current_user.id, today)
    return _to_out(
        item,
        _form_filled(db, current_user.id, today),
        _is_on_vacation(db, current_user.id, today),
    )


@router.patch("/today", response_model=DailyChecklistOut)
def update_today(
    payload: DailyChecklistUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kurýr může ručně odškrtnout jen 'auto' a 'natankováno'.
    Formulář se odškrtává automaticky přes /performance."""
    today = date_type.today()
    item = _get_or_create_today(db, current_user.id, today)
    if payload.car_checked is not None:
        item.car_checked = payload.car_checked
    if payload.refueled is not None:
        item.refueled = payload.refueled
    db.commit()
    db.refresh(item)
    return _to_out(
        item,
        _form_filled(db, current_user.id, today),
        _is_on_vacation(db, current_user.id, today),
    )
