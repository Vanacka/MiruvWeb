import calendar
from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user, require_admin
from models import User, UserRole, VacationDay, VacationStatus
from schemas import (
    VacationRequestCreate, VacationRangeRequestCreate, VacationDayOut, VacationDayColor,
)
from holidays import is_czech_state_holiday, czech_state_holiday_name

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
    if payload.date.weekday() >= 5 or is_czech_state_holiday(payload.date):
        raise HTTPException(400, "Na víkend nebo státní svátek nejde dovolenou vzít - tehdy se stejně nepracuje.")

    existing = db.query(VacationDay).filter(
        VacationDay.user_id == current_user.id,
        VacationDay.date == payload.date,
        VacationDay.status != VacationStatus.rejected,
    ).first()
    if existing:
        raise HTTPException(400, "Na tento den už máš žádost o dovolenou")

    # Počítá se i čekající (ne jen schválená) dovolená - jinak by šlo nabrat
    # pending žádostí přes limit a čekat, až je admin (nevědomky) schválí.
    used_days = db.query(VacationDay).filter(
        VacationDay.user_id == current_user.id,
        VacationDay.status.in_([VacationStatus.approved, VacationStatus.pending]),
    ).count()
    if used_days >= current_user.vacation_days_limit:
        raise HTTPException(400, "Vyčerpal jsi limit dní na dovolenou")

    entry = VacationDay(user_id=current_user.id, date=payload.date, status=VacationStatus.pending)
    db.add(entry)
    db.flush()
    entry.request_group_id = entry.id  # jednodenní žádost = skupina o jednom dni
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/range", response_model=list[VacationDayOut])
def request_vacation_range(
    payload: VacationRangeRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Žádost o dovolenou na celé období najednou - víkendy a státní svátky se
    v rozsahu tiše přeskočí (dovolenou stejně nejde vzít, viz request_vacation).
    Atomické: dokud neprojdou všechny kontroly, nic se nezapíše."""
    if payload.end_date < payload.start_date:
        raise HTTPException(400, "Konec období nesmí být před začátkem")

    span_days = (payload.end_date - payload.start_date).days
    all_dates = [payload.start_date + timedelta(days=i) for i in range(span_days + 1)]
    workdays = [d for d in all_dates if d.weekday() < 5 and not is_czech_state_holiday(d)]
    if not workdays:
        raise HTTPException(400, "Ve zvoleném období nejsou žádné pracovní dny")

    conflicting = db.query(VacationDay.date).filter(
        VacationDay.user_id == current_user.id,
        VacationDay.date.in_(workdays),
        VacationDay.status != VacationStatus.rejected,
    ).all()
    if conflicting:
        first = min(d for (d,) in conflicting)
        raise HTTPException(400, f"Na {first.isoformat()} už máš žádost o dovolenou")

    used_days = db.query(VacationDay).filter(
        VacationDay.user_id == current_user.id,
        VacationDay.status.in_([VacationStatus.approved, VacationStatus.pending]),
    ).count()
    remaining = current_user.vacation_days_limit - used_days
    if len(workdays) > remaining:
        raise HTTPException(
            400,
            f"Žádáš o {len(workdays)} pracovních dní, ale zbývá ti jen {remaining} z limitu dovolené",
        )

    entries = [VacationDay(user_id=current_user.id, date=d, status=VacationStatus.pending) for d in workdays]
    db.add_all(entries)
    db.flush()
    group_id = entries[0].id
    for e in entries:
        e.request_group_id = group_id
    db.commit()
    for e in entries:
        db.refresh(e)
    return entries


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
    db.flush()
    entry.request_group_id = entry.id
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


@router.patch("/group/{group_id}/approve", response_model=list[VacationDayOut])
def approve_vacation_group(group_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Schválí najednou celé období (všechny čekající dny se stejným request_group_id)."""
    entries = db.query(VacationDay).filter(
        VacationDay.request_group_id == group_id, VacationDay.status == VacationStatus.pending,
    ).all()
    if not entries:
        raise HTTPException(404, "Žádost nenalezena")
    for e in entries:
        e.status = VacationStatus.approved
    db.commit()
    for e in entries:
        db.refresh(e)
    return entries


@router.patch("/group/{group_id}/reject", response_model=list[VacationDayOut])
def reject_vacation_group(group_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    entries = db.query(VacationDay).filter(
        VacationDay.request_group_id == group_id, VacationDay.status == VacationStatus.pending,
    ).all()
    if not entries:
        raise HTTPException(404, "Žádost nenalezena")
    for e in entries:
        e.status = VacationStatus.rejected
    db.commit()
    for e in entries:
        db.refresh(e)
    return entries


@router.delete("/{vacation_id}")
def delete_vacation(
    vacation_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Kurýr smí zrušit vlastní žádost o dovolenou (čekající i už schválenou) -
    plány se můžou změnit. Admin smí zrušit kteroukoliv."""
    entry = db.query(VacationDay).filter(VacationDay.id == vacation_id).first()
    if not entry:
        raise HTTPException(404, "Žádost nenalezena")
    if current_user.role != UserRole.admin and entry.user_id != current_user.id:
        raise HTTPException(403, "Nemáš oprávnění zrušit tuto žádost")
    db.delete(entry)
    db.commit()
    return {"ok": True}


@router.get("/mine", response_model=list[VacationDayOut])
def my_vacations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(VacationDay).filter(VacationDay.user_id == current_user.id).all()


@router.get("/pending", response_model=list[VacationDayOut])
def pending_vacations(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(VacationDay).filter(VacationDay.status == VacationStatus.pending).all()


@router.get("/calendar", response_model=list[VacationDayColor])
def calendar_view(
    year: int, month: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Barevný kalendář pro daný měsíc - modrá (moje schválená) > šedá (víkend/svátek)
    > červená (obsazeno) > žlutá (čeká) > zelená (volno)."""
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
        is_weekend = d.weekday() >= 5
        is_holiday = is_czech_state_holiday(d)
        holiday_name = czech_state_holiday_name(d) if is_holiday else None
        mine_approved = any(e.user_id == current_user.id for e in approved)

        # Modrá vyhrává i nad víkendem/svátkem kvůli admin_add_vacation (ten
        # nekontroluje víkend/svátek) - vlastní schválený den se má vždy poznat.
        if mine_approved:
            color = "blue"
        elif is_weekend or is_holiday:
            color = "gray"
        elif len(approved) >= MAX_CONCURRENT_VACATIONS:
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
            is_weekend=is_weekend, is_holiday=is_holiday, holiday_name=holiday_name,
        ))
    return result
