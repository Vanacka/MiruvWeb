from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user, require_admin
from models import User, UserRole, DailyChecklist, PerformanceEntry, VacationDay, VacationStatus, Notification
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
    """Checklist se odškrtne jen když je záznam kompletně vyplněný (confirmed).
    Pokud kurýr ve wizardu něco přeskočil a uložil to jen jako rozpracované,
    záznam existuje, ale checklist zůstává neodškrtnutý."""
    return db.query(PerformanceEntry).filter(
        PerformanceEntry.user_id == user_id, PerformanceEntry.date == today,
        PerformanceEntry.confirmed == True,  # noqa: E712
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


def run_daily_incomplete_check(db: Session, day: date_type) -> int:
    """Pro daný den zkontroluje všechny aktivní uživatele (kurýry i admina, pokud
    ten den jel jako kurýr) a adminům pošle upozornění na každého, kdo nemá
    hotový celý checklist a zároveň nemá ten den schválenou dovolenou.
    Idempotentní přes DailyChecklist.notified_incomplete, aby stejný den
    neposílalo notifikace opakovaně (např. po restartu serveru).
    """
    admins = db.query(User).filter(User.role == UserRole.admin).all()
    if not admins:
        return 0

    notified = 0
    for u in db.query(User).filter(User.is_active == True).all():  # noqa: E712
        if _is_on_vacation(db, u.id, day):
            continue

        item = db.query(DailyChecklist).filter(
            DailyChecklist.user_id == u.id, DailyChecklist.date == day,
        ).first()
        if item and item.notified_incomplete:
            continue

        car_checked = item.car_checked if item else False
        refueled = item.refueled if item else False
        form_filled = _form_filled(db, u.id, day)
        if car_checked and refueled and form_filled:
            continue

        missing = []
        if not car_checked:
            missing.append("kontrola auta")
        if not refueled:
            missing.append("natankování")
        if not form_filled:
            missing.append("formulář trasy")

        for admin in admins:
            db.add(Notification(
                recipient_id=admin.id,
                message=f"{u.full_name} nemá za {day.isoformat()} hotovo: {', '.join(missing)}.",
            ))

        if not item:
            item = DailyChecklist(user_id=u.id, date=day)
            db.add(item)
        item.notified_incomplete = True
        notified += 1

    db.commit()
    return notified


@router.post("/run-daily-check")
def trigger_daily_check(
    target_date: Optional[date_type] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Ruční spuštění kontroly neúplných checklistů (jinak běží automaticky
    plánovačem na pozadí). Užitečné pro testování bez čekání na večer."""
    day = target_date or date_type.today()
    notified = run_daily_incomplete_check(db, day)
    return {"date": day, "notified": notified}
