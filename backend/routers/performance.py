import csv
import io
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user, require_admin
from models import (
    User, UserRole, Route, PerformanceEntry, Notification,
)
from schemas import (
    RouteCreate, RouteOut, RouteAssignmentUpdate, PerformanceEntryCreate, PerformanceEntryOut,
    PerformanceAverages,
)

router = APIRouter(prefix="/performance", tags=["performance"])


def _assert_route_allowed(user: User, route_id: int) -> None:
    """Admin smí vyplnit formulář na jakoukoliv trasu. Kurýr jen na svoje
    přiřazené preferované trasy - pokud zatím žádné nemá přiřazené, smí
    (dočasně) na kteroukoliv, aby nezůstal zaseknutý než mu je Mirek nastaví."""
    if user.role == UserRole.admin:
        return
    if user.preferred_routes and route_id not in {r.id for r in user.preferred_routes}:
        raise HTTPException(403, "Tato trasa není mezi tvými přiřazenými trasami")


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


# ---------- Záznamy výkonu ----------

@router.post("", response_model=PerformanceEntryOut)
def create_entry(
    payload: PerformanceEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _assert_route_allowed(current_user, payload.route_id)
    entry = PerformanceEntry(
        user_id=current_user.id,
        route_id=payload.route_id,
        date=payload.date,
        km_driven=payload.km_driven,
        packages_delivered=payload.packages_delivered,
        hours_worked=payload.hours_worked,
        note=payload.note,
        confirmed=payload.confirmed,
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

    return entry


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

    for field, value in payload.model_dump().items():
        setattr(entry, field, value)
    entry.updated_by_id = current_user.id
    db.commit()
    db.refresh(entry)
    return entry


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

    return entries


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
