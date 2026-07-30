import csv
import io
import re
import unicodedata
from datetime import date as date_type, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user, require_admin
from models import (
    User, UserRole, Route, PerformanceEntry, PerformanceEntryEdit, PerformanceEntryDispute,
    DisputeStatus, PerformanceFieldDefinition, Notification,
)
from schemas import (
    RouteCreate, RouteOut, RouteAssignmentUpdate, PerformanceFieldCreate, PerformanceFieldUpdate,
    PerformanceFieldOut, PerformanceEntryCreate, PerformanceEntryOut, PerformanceEntryEditOut,
    DisputeCreate, DisputeResolve, PerformanceEntryDisputeOut, PerformanceAverages,
)
from holidays import is_czech_state_holiday

# Sledovaná pole při úpravě záznamu - u těchto se do logu ukládá stará/nová hodnota.
# "skipped_fields" (a z něj odvozené "confirmed") se řeší zvlášť, viz update_entry.
_TRACKED_FIELDS = [
    "route_id", "date", "km_driven", "packages_delivered",
    "hours_worked", "note", "extra_fields",
]


def _jsonable(value: Any) -> Any:
    if isinstance(value, date_type):
        return value.isoformat()
    return value

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


def _assert_route_date_free(db: Session, route_id: int, date: date_type, exclude_entry_id: Optional[int] = None) -> None:
    """Na danou trasu a den smí existovat jen jeden záznam výkonu."""
    q = db.query(PerformanceEntry).filter(
        PerformanceEntry.route_id == route_id, PerformanceEntry.date == date,
    )
    if exclude_entry_id is not None:
        q = q.filter(PerformanceEntry.id != exclude_entry_id)
    if q.first():
        raise HTTPException(400, "Pro tuto trasu a den už formulář existuje - uprav stávající záznam.")


def _entry_to_out(entry: PerformanceEntry) -> PerformanceEntryOut:
    edits = entry.edits
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
        skipped_fields=entry.skipped_fields or [],
        updated_at=entry.updated_at,
        updated_by_id=entry.updated_by_id,
        is_weekend=entry.date.weekday() >= 5,
        is_holiday=is_czech_state_holiday(entry.date),
        edit_count=len(edits),
        is_late_edit=any(e.edited_at.date() > entry.date for e in edits),
    )


def _dispute_to_out(dispute: PerformanceEntryDispute) -> PerformanceEntryDisputeOut:
    conflicting = dispute.conflicting_entry
    return PerformanceEntryDisputeOut(
        id=dispute.id,
        route_id=dispute.route_id,
        route_name=dispute.route.name,
        date=dispute.date,
        status=dispute.status,
        reported_by_id=dispute.reported_by_id,
        reported_by_name=dispute.reported_by.full_name,
        proposed_km_driven=dispute.proposed_km_driven,
        proposed_packages_delivered=dispute.proposed_packages_delivered,
        proposed_hours_worked=dispute.proposed_hours_worked,
        proposed_note=dispute.proposed_note,
        proposed_confirmed=dispute.proposed_confirmed,
        proposed_extra_fields=dispute.proposed_extra_fields or {},
        conflicting_entry=_entry_to_out(conflicting),
        conflicting_entry_owner_name=conflicting.user.full_name,
        corrected_route_id=dispute.corrected_route_id,
        corrected_route_name=dispute.corrected_route.name if dispute.corrected_route else None,
        created_at=dispute.created_at,
        resolved_at=dispute.resolved_at,
        resolved_by_name=dispute.resolved_by.full_name if dispute.resolved_by else None,
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

    # Kurýr smí mít na jeden den jen jeden rozpracovaný/hotový záznam (bez ohledu na trasu) -
    # jakmile na něco začal odpovídat, nesmí si "omylem" založit další na jinou trasu.
    own_entry_today = db.query(PerformanceEntry).filter(
        PerformanceEntry.user_id == current_user.id, PerformanceEntry.date == payload.date,
    ).first()
    if own_entry_today:
        raise HTTPException(400, (
            f"Na {payload.date.isoformat()} už máš rozpracovaný nebo hotový formulář "
            f"(trasa {own_entry_today.route.name}) - dokonči nebo uprav ten."
        ))

    conflicting = db.query(PerformanceEntry).filter(
        PerformanceEntry.route_id == payload.route_id, PerformanceEntry.date == payload.date,
    ).first()
    if conflicting:
        raise HTTPException(409, detail={
            "message": f"Tuto trasu na {payload.date.isoformat()} už vyplnil {conflicting.user.full_name}.",
            "conflicting_entry_id": conflicting.id,
            "is_mine": False,
        })

    skipped = payload.skipped_fields or []
    entry = PerformanceEntry(
        user_id=current_user.id,
        route_id=payload.route_id,
        date=payload.date,
        km_driven=payload.km_driven,
        packages_delivered=payload.packages_delivered,
        hours_worked=payload.hours_worked,
        note=payload.note,
        extra_fields=payload.extra_fields,
        skipped_fields=skipped,
        confirmed=not skipped,
        updated_by_id=current_user.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    # Pokud něco zůstalo nevyplněné, upozorni adminy
    if skipped:
        admins = db.query(User).filter(User.role == UserRole.admin).all()
        for admin in admins:
            db.add(Notification(
                recipient_id=admin.id,
                message=f"{current_user.full_name} nedokončil formulář výkonu za {payload.date}",
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
    if payload.route_id != entry.route_id or payload.date != entry.date:
        _assert_route_date_free(db, payload.route_id, payload.date, exclude_entry_id=entry.id)
        if payload.date != entry.date:
            own_clash = db.query(PerformanceEntry).filter(
                PerformanceEntry.user_id == entry.user_id, PerformanceEntry.date == payload.date,
                PerformanceEntry.id != entry.id,
            ).first()
            if own_clash:
                raise HTTPException(400, "Na tento den už máš jiný záznam.")

    changes = {}
    for field in _TRACKED_FIELDS:
        old_value = getattr(entry, field)
        new_value = getattr(payload, field)
        if old_value != new_value:
            changes[field] = {"old": _jsonable(old_value), "new": _jsonable(new_value)}

    for field, value in payload.model_dump(exclude={"skipped_fields"}).items():
        setattr(entry, field, value)
    entry.updated_by_id = current_user.id

    # skipped_fields (a z něj odvozené confirmed) se mění, jen když je explicitně poslané -
    # ruční oprava přes plochý formulář ho neposílá a stav vyplnění tak zůstává nedotčený.
    if payload.skipped_fields is not None:
        if payload.skipped_fields != (entry.skipped_fields or []):
            changes["skipped_fields"] = {
                "old": entry.skipped_fields or [], "new": payload.skipped_fields,
            }
        entry.skipped_fields = payload.skipped_fields
        entry.confirmed = not payload.skipped_fields

    if changes:
        db.add(PerformanceEntryEdit(
            entry_id=entry.id, edited_by_id=current_user.id, changes=changes,
        ))

    db.commit()
    db.refresh(entry)
    return _entry_to_out(entry)


@router.get("/{entry_id}/edits", response_model=list[PerformanceEntryEditOut])
def list_entry_edits(entry_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    entry = db.query(PerformanceEntry).filter(PerformanceEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Záznam nenalezen")
    return [
        PerformanceEntryEditOut(
            id=e.id, edited_by_id=e.edited_by_id, edited_by_name=e.edited_by.full_name,
            edited_at=e.edited_at, changes=e.changes or {},
        )
        for e in entry.edits
    ]


# ---------- Nahlášené chyby (kolize na trase/dni) ----------

@router.post("/disputes", response_model=PerformanceEntryDisputeOut)
def create_dispute(
    payload: DisputeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kurýr nahlásí, že na tuto trasu/den už omylem vyplnil formulář někdo jiný.
    Nic se nezapíše do performance_entries - jen se pošle admin(ům) ke schválení."""
    conflicting = db.query(PerformanceEntry).filter(
        PerformanceEntry.route_id == payload.route_id, PerformanceEntry.date == payload.date,
    ).first()
    if not conflicting:
        raise HTTPException(400, "Pro tuto trasu a den zatím žádný záznam neexistuje - vyplň ho normálně.")
    if conflicting.user_id == current_user.id:
        raise HTTPException(400, "Tohle je tvůj vlastní záznam - uprav ho místo nahlašování chyby.")

    existing_dispute = db.query(PerformanceEntryDispute).filter(
        PerformanceEntryDispute.route_id == payload.route_id,
        PerformanceEntryDispute.date == payload.date,
        PerformanceEntryDispute.status == DisputeStatus.pending,
    ).first()
    if existing_dispute:
        raise HTTPException(400, "Na tuto trasu a den už čeká nahlášená chyba na vyřízení.")

    dispute = PerformanceEntryDispute(
        route_id=payload.route_id,
        date=payload.date,
        conflicting_entry_id=conflicting.id,
        reported_by_id=current_user.id,
        proposed_km_driven=payload.km_driven,
        proposed_packages_delivered=payload.packages_delivered,
        proposed_hours_worked=payload.hours_worked,
        proposed_note=payload.note,
        proposed_confirmed=payload.confirmed,
        proposed_extra_fields=payload.extra_fields,
    )
    db.add(dispute)
    db.commit()
    db.refresh(dispute)

    admins = db.query(User).filter(User.role == UserRole.admin).all()
    for admin in admins:
        db.add(Notification(
            recipient_id=admin.id,
            message=(
                f"{current_user.full_name} nahlásil chybu na trase '{conflicting.route.name}' "
                f"({payload.date.isoformat()}) - formulář tam vyplnil {conflicting.user.full_name}."
            ),
        ))
    db.commit()

    return _dispute_to_out(dispute)


@router.get("/disputes", response_model=list[PerformanceEntryDisputeOut])
def list_disputes(
    status: Optional[DisputeStatus] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = db.query(PerformanceEntryDispute)
    if status:
        q = q.filter(PerformanceEntryDispute.status == status)
    disputes = q.order_by(PerformanceEntryDispute.created_at.desc()).all()
    return [_dispute_to_out(d) for d in disputes]


@router.post("/disputes/{dispute_id}/approve", response_model=PerformanceEntryDisputeOut)
def approve_dispute(
    dispute_id: int,
    payload: DisputeResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    dispute = db.query(PerformanceEntryDispute).filter(PerformanceEntryDispute.id == dispute_id).first()
    if not dispute:
        raise HTTPException(404, "Spor nenalezen")
    if dispute.status != DisputeStatus.pending:
        raise HTTPException(400, "Tento spor už byl vyřízen")
    if payload.corrected_route_id == dispute.route_id:
        raise HTTPException(400, "Opravená trasa musí být jiná než ta sporná")
    if not db.query(Route).filter(Route.id == payload.corrected_route_id).first():
        raise HTTPException(404, "Opravená trasa nenalezena")

    conflicting = dispute.conflicting_entry
    old_route_id = conflicting.route_id
    if payload.corrected_route_id != old_route_id:
        db.add(PerformanceEntryEdit(
            entry_id=conflicting.id,
            edited_by_id=current_user.id,
            changes={"route_id": {"old": old_route_id, "new": payload.corrected_route_id}},
        ))
        conflicting.route_id = payload.corrected_route_id
        conflicting.updated_by_id = current_user.id

    new_entry = PerformanceEntry(
        user_id=dispute.reported_by_id,
        route_id=dispute.route_id,
        date=dispute.date,
        km_driven=dispute.proposed_km_driven,
        packages_delivered=dispute.proposed_packages_delivered,
        hours_worked=dispute.proposed_hours_worked,
        note=dispute.proposed_note,
        confirmed=dispute.proposed_confirmed,
        extra_fields=dispute.proposed_extra_fields or {},
        updated_by_id=dispute.reported_by_id,
    )
    db.add(new_entry)

    dispute.status = DisputeStatus.approved
    dispute.corrected_route_id = payload.corrected_route_id
    dispute.resolved_at = datetime.utcnow()
    dispute.resolved_by_id = current_user.id

    db.commit()
    db.refresh(dispute)
    return _dispute_to_out(dispute)


@router.post("/disputes/{dispute_id}/reject", response_model=PerformanceEntryDisputeOut)
def reject_dispute(
    dispute_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin),
):
    dispute = db.query(PerformanceEntryDispute).filter(PerformanceEntryDispute.id == dispute_id).first()
    if not dispute:
        raise HTTPException(404, "Spor nenalezen")
    if dispute.status != DisputeStatus.pending:
        raise HTTPException(400, "Tento spor už byl vyřízen")

    dispute.status = DisputeStatus.rejected
    dispute.resolved_at = datetime.utcnow()
    dispute.resolved_by_id = current_user.id
    db.commit()
    db.refresh(dispute)
    return _dispute_to_out(dispute)


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
