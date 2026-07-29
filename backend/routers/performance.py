import csv
import io
import re
import unicodedata
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user, require_admin
from models import (
    User, UserRole, Route, PerformanceEntry, PerformanceFieldDefinition, Notification,
)
from schemas import (
    RouteCreate, RouteOut, RouteAssignmentUpdate, PerformanceFieldCreate, PerformanceFieldUpdate,
    PerformanceFieldOut, PerformanceEntryCreate, PerformanceEntryOut, PerformanceAverages,
)
from holidays import is_czech_state_holiday

router = APIRouter(prefix="/performance", tags=["performance"])


def _assert_route_allowed(user: User, route_id: int) -> None:
    """Admin smí vyplnit formulář na jakoukoliv trasu. Kurýr jen na svoje
    přiřazené preferované trasy - pokud zatím žádné nemá přiřazené, smí
    (dočasně) na kteroukoliv, aby nezůstal zaseknutý než mu je Mirek nastaví."""
    if user.role == UserRole.admin:
        return
    if user.preferred_routes and route_id not in {r.id for r in user.preferred_routes}:
        raise HTTPException(403, "Tato trasa není mezi tvými přiřazenými trasami")


def _validate_extra_fields(db: Session, extra_fields: dict) -> None:
    active_fields = db.query(PerformanceFieldDefinition).filter(
        PerformanceFieldDefinition.active == True  # noqa: E712
    ).all()
    for f in active_fields:
        if f.required and not str(extra_fields.get(f.key, "")).strip():
            raise HTTPException(400, f"Pole '{f.label}' je povinné")


def _entry_to_out(entry: PerformanceEntry) -> PerformanceEntryOut:
    return PerformanceEntryOut(
        id=entry.id,
        user_id=entry.user_id,
        route_id=entry.route_id,
        date=entry.date,
        km_driven=entry.km_driven,
        packages_delivered=entry.packages_delivered,
        hours_worked=entry.hours_worked,
        note=entry.note,
        confirmed=entry.confirmed,
        extra_fields=entry.extra_fields or {},
        updated_at=entry.updated_at,
        updated_by_id=entry.updated_by_id,
        is_weekend=entry.date.weekday() >= 5,
        is_holiday=is_czech_state_holiday(entry.date),
    )


def _slugify_field_key(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label)
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_str.strip().lower()).strip("_")
    return slug or "field"


# ---------- Trasy ----------

@router.post("/routes", response_model=RouteOut)
def create_route(payload: RouteCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if db.query(Route).filter(Route.name == payload.name).first():
        raise HTTPException(400, "Trasa s tímto názvem už existuje")
    route = Route(name=payload.name)
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


@router.get("/routes", response_model=list[RouteOut])
def list_routes(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Route).all()


@router.get("/routes/mine", response_model=list[RouteOut])
def my_routes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Trasy, které smí aktuální uživatel vyplňovat ve formuláři výkonu.
    Bez přiřazení (ještě nenastaveno, nebo admin) vidí všechny."""
    if current_user.role != UserRole.admin and current_user.preferred_routes:
        return current_user.preferred_routes
    return db.query(Route).all()


@router.get("/routes/assignments/{user_id}", response_model=list[RouteOut])
def get_route_assignments(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Uživatel nenalezen")
    return user.preferred_routes


@router.put("/routes/assignments/{user_id}", response_model=list[RouteOut])
def set_route_assignments(
    user_id: int,
    payload: RouteAssignmentUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Uživatel nenalezen")
    routes = db.query(Route).filter(Route.id.in_(payload.route_ids)).all()
    user.preferred_routes = routes
    db.commit()
    db.refresh(user)
    return user.preferred_routes


# ---------- Vlastní pole formuláře ----------

@router.get("/fields", response_model=list[PerformanceFieldOut])
def list_fields(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Všechna pole (i neaktivní) - pro admin správu."""
    return db.query(PerformanceFieldDefinition).order_by(PerformanceFieldDefinition.position).all()


@router.get("/fields/active", response_model=list[PerformanceFieldOut])
def list_active_fields(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Aktivní pole - pro vykreslení formuláře kurýrům."""
    return db.query(PerformanceFieldDefinition).filter(
        PerformanceFieldDefinition.active == True  # noqa: E712
    ).order_by(PerformanceFieldDefinition.position).all()


@router.post("/fields", response_model=PerformanceFieldOut)
def create_field(
    payload: PerformanceFieldCreate, db: Session = Depends(get_db), _: User = Depends(require_admin),
):
    base_key = _slugify_field_key(payload.label)
    key = base_key
    n = 2
    while db.query(PerformanceFieldDefinition).filter(PerformanceFieldDefinition.key == key).first():
        key = f"{base_key}_{n}"
        n += 1
    max_position = db.query(func.max(PerformanceFieldDefinition.position)).scalar() or 0
    field = PerformanceFieldDefinition(
        key=key, label=payload.label, field_type=payload.field_type,
        required=payload.required, position=max_position + 1,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.patch("/fields/{field_id}", response_model=PerformanceFieldOut)
def update_field(
    field_id: int,
    payload: PerformanceFieldUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    field = db.query(PerformanceFieldDefinition).filter(PerformanceFieldDefinition.id == field_id).first()
    if not field:
        raise HTTPException(404, "Pole nenalezeno")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(field, key, value)
    db.commit()
    db.refresh(field)
    return field


# ---------- Záznamy výkonu ----------

@router.post("", response_model=PerformanceEntryOut)
def create_entry(
    payload: PerformanceEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _assert_route_allowed(current_user, payload.route_id)
    _validate_extra_fields(db, payload.extra_fields)
    entry = PerformanceEntry(
        user_id=current_user.id,
        route_id=payload.route_id,
        date=payload.date,
        km_driven=payload.km_driven,
        packages_delivered=payload.packages_delivered,
        hours_worked=payload.hours_worked,
        note=payload.note,
        confirmed=payload.confirmed,
        extra_fields=payload.extra_fields,
        updated_by_id=current_user.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    # Pokud kurýr nezaškrtl potvrzovací checkbox, upozorni Mirka
    if not payload.confirmed:
        admins = db.query(User).filter(User.role == UserRole.admin).all()
        for admin in admins:
            db.add(Notification(
                recipient_id=admin.id,
                message=f"{current_user.full_name} neodškrtl formulář výkonu za {payload.date}",
            ))
        db.commit()

    return _entry_to_out(entry)


@router.patch("/{entry_id}", response_model=PerformanceEntryOut)
def update_entry(
    entry_id: int,
    payload: PerformanceEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mirek (nebo autor) může záznam upravit - historie editace se ukládá do updated_at/updated_by."""
    entry = db.query(PerformanceEntry).filter(PerformanceEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Záznam nenalezen")
    if current_user.role != UserRole.admin and entry.user_id != current_user.id:
        raise HTTPException(403, "Nemáš oprávnění upravit tento záznam")
    _assert_route_allowed(current_user, payload.route_id)
    _validate_extra_fields(db, payload.extra_fields)

    for field, value in payload.model_dump().items():
        setattr(entry, field, value)
    entry.updated_by_id = current_user.id
    db.commit()
    db.refresh(entry)
    return _entry_to_out(entry)


@router.get("", response_model=list[PerformanceEntryOut])
def list_entries(
    route_id: Optional[int] = None,
    user_id: Optional[int] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    day: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(PerformanceEntry)
    if current_user.role != UserRole.admin:
        q = q.filter(PerformanceEntry.user_id == current_user.id)
    elif user_id:
        q = q.filter(PerformanceEntry.user_id == user_id)

    if route_id:
        q = q.filter(PerformanceEntry.route_id == route_id)
    entries = q.all()

    if year:
        entries = [e for e in entries if e.date.year == year]
    if month:
        entries = [e for e in entries if e.date.month == month]
    if day:
        entries = [e for e in entries if e.date.day == day]

    return [_entry_to_out(e) for e in entries]


@router.get("/export.csv")
def export_csv(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = db.query(PerformanceEntry).all()
    if year:
        q = [e for e in q if e.date.year == year]
    if month:
        q = [e for e in q if e.date.month == month]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["datum", "kuryr", "trasa", "km", "zasilky", "hodiny", "potvrzeno", "poznamka"])
    for e in q:
        writer.writerow([
            e.date, e.user.full_name, e.route.name,
            e.km_driven, e.packages_delivered, e.hours_worked,
            "ano" if e.confirmed else "ne", e.note or "",
        ])
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vykon.csv"},
    )


@router.get("/averages", response_model=list[PerformanceAverages])
def averages(
    year: int, month: int,
    db: Session = Depends(get_db), _: User = Depends(require_admin),
):
    users = db.query(User).filter(User.role == UserRole.courier).all()
    result = []
    for u in users:
        entries = [
            e for e in db.query(PerformanceEntry).filter(PerformanceEntry.user_id == u.id).all()
            if e.date.year == year and e.date.month == month
        ]
        count = len(entries)
        result.append(PerformanceAverages(
            user_id=u.id, full_name=u.full_name,
            avg_km=(sum(e.km_driven for e in entries) / count) if count else 0,
            avg_packages=(sum(e.packages_delivered for e in entries) / count) if count else 0,
            avg_hours=(sum(e.hours_worked for e in entries) / count) if count else 0,
            entries_count=count,
        ))
    return result
