import calendar
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user, require_admin
from models import User, UserRole, VacationDay, VacationStatus
from schemas import VacationRequestCreate, VacationDayOut, VacationDayColor

router = APIRouter(prefix="/vacation", tags=["vacation"])

# Kolik lidí smí mít současně schválenou dovolenou na stejný den, než se den
# stane "červeným" (nejde už na něj dovolenou vzít). Uprav dle reálného provozu.
MAX_CONCURRENT_VACATIONS = 1


@router.post("", response_model=VacationDayOut)
def request_vacation(
    payload: VacationRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(VacationDay).filter(
        VacationDay.user_id == current_user.id,
        VacationDay.date == payload.date,
        VacationDay.status != VacationStatus.rejected,
    ).first()
    if existing:
        raise HTTPException(400, "Na tento den už máš žádost o dovolenou")

    used_days = db.query(VacationDay).filter(
        VacationDay.user_id == current_user.id,
        VacationDay.status == VacationStatus.approved,
    ).count()
    if used_days >= current_user.vacation_days_limit:
        raise HTTPException(400, "Vyčerpal jsi limit dní na dovolenou")

    entry = VacationDay(user_id=current_user.id, date=payload.date, status=VacationStatus.pending)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/admin", response_model=VacationDayOut)
def admin_add_vacation(
    payload: VacationRequestCreate,
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Mirek rovnou zadává dovolenou za kurýra, bez schvalovacího procesu."""
    entry = VacationDay(
        user_id=user_id, date=payload.date,
        status=VacationStatus.approved, created_by_admin=True,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{vacation_id}/approve", response_model=VacationDayOut)
def approve_vacation(vacation_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    entry = db.query(VacationDay).filter(VacationDay.id == vacation_id).first()
    if not entry:
        raise HTTPException(404, "Žádost nenalezena")
    entry.status = VacationStatus.approved
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{vacation_id}/reject", response_model=VacationDayOut)
def reject_vacation(vacation_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    entry = db.query(VacationDay).filter(VacationDay.id == vacation_id).first()
    if not entry:
        raise HTTPException(404, "Žádost nenalezena")
    entry.status = VacationStatus.rejected
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/mine", response_model=list[VacationDayOut])
def my_vacations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(VacationDay).filter(VacationDay.user_id == current_user.id).all()


@router.get("/pending", response_model=list[VacationDayOut])
def pending_vacations(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(VacationDay).filter(VacationDay.status == VacationStatus.pending).all()


@router.get("/calendar", response_model=list[VacationDayColor])
def calendar_view(year: int, month: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Barevný kalendář pro daný měsíc - green/yellow/red podle obsazenosti."""
    _, days_in_month = calendar.monthrange(year, month)
    entries = db.query(VacationDay).filter(
        VacationDay.date >= date_type(year, month, 1),
        VacationDay.date <= date_type(year, month, days_in_month),
        VacationDay.status != VacationStatus.rejected,
    ).all()

    result = []
    for day in range(1, days_in_month + 1):
        d = date_type(year, month, day)
        day_entries = [e for e in entries if e.date == d]
        approved = [e for e in day_entries if e.status == VacationStatus.approved]
        pending = [e for e in day_entries if e.status == VacationStatus.pending]

        if len(approved) >= MAX_CONCURRENT_VACATIONS:
            color = "red"
        elif pending:
            color = "yellow"
        else:
            color = "green"

        approved_names = [e.user.full_name for e in approved]
        pending_names = [e.user.full_name for e in pending]
        result.append(VacationDayColor(
            date=d, color=color,
            approved_users=approved_names, pending_users=pending_names,
        ))
    return result
