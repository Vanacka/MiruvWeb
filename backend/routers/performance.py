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
    "route_id", "date", "pocet_hd", "pocet_boxy", "hd_psd_box",
    "svoz_do_50", "svoz_do_100", "svoz_nad_100", "dobirky", "pocet_baliku",
    "nedorucene", "km", "note", "extra_fields",
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


def _assert_no_skip_if_backdated(user: User, payload: PerformanceEntryCreate) -> None:
    """Kurýr nesmí při zpětném vyplňování (jiný den než dnešek) nic nechat 'na
    později' - termín už stejně minul. Admin smí i tak dělat zpětné opravy po částech."""
    if user.role == UserRole.admin:
        return
    if payload.date != date_type.today() and payload.skipped_fields:
        raise HTTPException(400, "Zpětně vyplňovaný formulář nejde uložit s nedokončenými položkami.")


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
        pocet_hd=entry.pocet_hd,
        pocet_boxy=entry.pocet_boxy,
        hd_psd_box=entry.hd_psd_box,
        svoz_do_50=entry.svoz_do_50,
        svoz_do_100=entry.svoz_do_100,
        svoz_nad_100=entry.svoz_nad_100,
        dobirky=entry.dobirky,
        pocet_baliku=entry.pocet_baliku,
        nedorucene=entry.nedorucene,
        km=entry.km,
        note=entry.note,
        confirmed=entry.confirmed,
        extra_fields=entry.extra_fields or {},
        skipped_fields=entry.skipped_fields or [],
        updated_at=entry.updated_at,
        updated_by_id=entry.updated_by_id,
        is_weekend=entry.date.weekday() >= 5,
        is_holiday=is_czech_state_holiday(entry.date),
        edit_count=len(edits),
        is_late_creation=entry.created_at.date() > entry.date,
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
        proposed_pocet_hd=dispute.proposed_pocet_hd,
        proposed_pocet_boxy=dispute.proposed_pocet_boxy,
        proposed_hd_psd_box=dispute.proposed_hd_psd_box,
        proposed_svoz_do_50=dispute.proposed_svoz_do_50,
        proposed_svoz_do_100=dispute.proposed_svoz_do_100,
        proposed_svoz_nad_100=dispute.proposed_svoz_nad_100,
        proposed_dobirky=dispute.proposed_dobirky,
        proposed_pocet_baliku=dispute.proposed_pocet_baliku,
        proposed_nedorucene=dispute.proposed_nedorucene,
        proposed_km=dispute.proposed_km,
        proposed_note=dispute.proposed_note,
        proposed_confirmed=dispute.proposed_confirmed,
        proposed_extra_fields=dispute.proposed_extra_fields or {},
        proposed_skipped_fields=dispute.proposed_skipped_fields or [],
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


@router.delete("/routes/{route_id}")
def delete_route(route_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Trasu jde smazat, jen dokud na ni nikdy nikdo nevyplnil formulář výkonu -
    jinak by se zbořila historie záznamů, co na ni odkazují."""
    route = db.query(Route).filter(Route.id == route_id).first()
    if not route:
        raise HTTPException(404, "Trasa nenalezena")
    if db.query(PerformanceEntry).filter(PerformanceEntry.route_id == route_id).first():
        raise HTTPException(400, "Na tuto trasu už existují záznamy výkonu - nejdřív je smaž nebo přesuň.")
    route.preferred_by = []
    db.delete(route)
    db.commit()
    return {"ok": True}


@router.get("/routes/mine", response_model=list[RouteOut])
def my_routes(
    date: Optional[date_type] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trasy, které smí aktuální uživatel vyplňovat ve formuláři výkonu.
    Bez přiřazení (ještě nenastaveno, nebo admin) vidí všechny.
    Když je zadané datum, odfiltrují se trasy, na které už ten den někdo vyplnil
    formulář - ať si dva lidi nezvolí omylem tu samou. Kdo o svoji (obsazenou)
    trasu potřebuje nahlásit chybu, použije tlačítko "Nemohu vybrat svoji trasu",
    které rovnou založí hlášení chyby (POST /disputes) na kteroukoliv trasu."""
    if current_user.role != UserRole.admin and current_user.preferred_routes:
        candidate_routes = list(current_user.preferred_routes)
    else:
        candidate_routes = db.query(Route).all()
    if date is None:
        return candidate_routes
    taken_ids = {
        r_id for (r_id,) in db.query(PerformanceEntry.route_id)
        .filter(PerformanceEntry.date == date).all()
    }
    return [r for r in candidate_routes if r.id not in taken_ids]


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
    _assert_no_skip_if_backdated(current_user, payload)

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
        pocet_hd=payload.pocet_hd,
        pocet_boxy=payload.pocet_boxy,
        hd_psd_box=payload.hd_psd_box,
        svoz_do_50=payload.svoz_do_50,
        svoz_do_100=payload.svoz_do_100,
        svoz_nad_100=payload.svoz_nad_100,
        dobirky=payload.dobirky,
        pocet_baliku=payload.pocet_baliku,
        nedorucene=payload.nedorucene,
        km=payload.km,
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
    _assert_no_skip_if_backdated(current_user, payload)
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


@router.delete("/{entry_id}")
def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kurýr smí smazat jen svůj vlastní záznam (z libovolného dne), admin kterýkoliv."""
    entry = db.query(PerformanceEntry).filter(PerformanceEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Záznam nenalezen")
    if current_user.role != UserRole.admin and entry.user_id != current_user.id:
        raise HTTPException(403, "Nemáš oprávnění smazat tento záznam")

    linked_dispute = db.query(PerformanceEntryDispute).filter(
        PerformanceEntryDispute.conflicting_entry_id == entry.id,
    ).first()
    if linked_dispute:
        raise HTTPException(400, "Tento záznam je součástí nahlášené chyby - nejdřív ji vyřiď, pak půjde smazat.")

    db.query(PerformanceEntryEdit).filter(PerformanceEntryEdit.entry_id == entry.id).delete()
    db.delete(entry)
    db.commit()
    return {"ok": True}


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

def _apply_dispute_payload(dispute: PerformanceEntryDispute, payload: DisputeCreate) -> None:
    dispute.proposed_pocet_hd = payload.pocet_hd
    dispute.proposed_pocet_boxy = payload.pocet_boxy
    dispute.proposed_hd_psd_box = payload.hd_psd_box
    dispute.proposed_svoz_do_50 = payload.svoz_do_50
    dispute.proposed_svoz_do_100 = payload.svoz_do_100
    dispute.proposed_svoz_nad_100 = payload.svoz_nad_100
    dispute.proposed_dobirky = payload.dobirky
    dispute.proposed_pocet_baliku = payload.pocet_baliku
    dispute.proposed_nedorucene = payload.nedorucene
    dispute.proposed_km = payload.km
    dispute.proposed_note = payload.note
    dispute.proposed_confirmed = payload.confirmed
    dispute.proposed_extra_fields = payload.extra_fields
    dispute.proposed_skipped_fields = payload.skipped_fields


@router.post("/disputes", response_model=PerformanceEntryDisputeOut)
def create_dispute(
    payload: DisputeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kurýr nahlásí, že na tuto trasu/den už omylem vyplnil formulář někdo jiný.
    Nic se nezapíše do performance_entries - jen se pošle admin(ům) ke schválení.
    Pokud stejný kurýr na tutéž trasu/den už čekající hlášení má (typicky se vrací
    doplnit rozpracovaný formulář), přepíše se jím - ať nemusí začínat od nuly."""
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
        if existing_dispute.reported_by_id != current_user.id:
            raise HTTPException(400, "Na tuto trasu a den už čeká nahlášená chyba na vyřízení.")
        _apply_dispute_payload(existing_dispute, payload)
        existing_dispute.conflicting_entry_id = conflicting.id
        db.commit()
        db.refresh(existing_dispute)
        return _dispute_to_out(existing_dispute)

    dispute = PerformanceEntryDispute(
        route_id=payload.route_id,
        date=payload.date,
        conflicting_entry_id=conflicting.id,
        reported_by_id=current_user.id,
    )
    _apply_dispute_payload(dispute, payload)
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


@router.get("/disputes/mine", response_model=list[PerformanceEntryDisputeOut])
def my_disputes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Vlastní nahlášené chyby - kurýr si tak může dohledat rozpracované/čekající
    hlášení a pokračovat v jeho vyplňování, místo aby začínal znovu od nuly."""
    disputes = db.query(PerformanceEntryDispute).filter(
        PerformanceEntryDispute.reported_by_id == current_user.id,
    ).order_by(PerformanceEntryDispute.created_at.desc()).all()
    return [_dispute_to_out(d) for d in disputes]


@router.patch("/disputes/{dispute_id}", response_model=PerformanceEntryDisputeOut)
def update_dispute(
    dispute_id: int,
    payload: DisputeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kurýr doplní/opraví svoje dřív podané (a zatím nevyřízené) hlášení chyby."""
    dispute = db.query(PerformanceEntryDispute).filter(PerformanceEntryDispute.id == dispute_id).first()
    if not dispute:
        raise HTTPException(404, "Spor nenalezen")
    if dispute.reported_by_id != current_user.id:
        raise HTTPException(403, "Nemáš oprávnění upravit toto hlášení")
    if dispute.status != DisputeStatus.pending:
        raise HTTPException(400, "Tento spor už byl vyřízen, nejde upravit")
    _apply_dispute_payload(dispute, payload)
    db.commit()
    db.refresh(dispute)
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

    proposed_skipped = dispute.proposed_skipped_fields or []
    new_entry = PerformanceEntry(
        user_id=dispute.reported_by_id,
        route_id=dispute.route_id,
        date=dispute.date,
        pocet_hd=dispute.proposed_pocet_hd,
        pocet_boxy=dispute.proposed_pocet_boxy,
        hd_psd_box=dispute.proposed_hd_psd_box,
        svoz_do_50=dispute.proposed_svoz_do_50,
        svoz_do_100=dispute.proposed_svoz_do_100,
        svoz_nad_100=dispute.proposed_svoz_nad_100,
        dobirky=dispute.proposed_dobirky,
        pocet_baliku=dispute.proposed_pocet_baliku,
        nedorucene=dispute.proposed_nedorucene,
        km=dispute.proposed_km,
        note=dispute.proposed_note,
        # "confirmed" se odvozuje ze skipped_fields stejně jako u běžného vyplnění
        # (viz create_entry) - proposed_confirmed z hlášení chyby se ignoruje, ať
        # oba stavy nemůžou být nekonzistentní.
        confirmed=not proposed_skipped,
        extra_fields=dispute.proposed_extra_fields or {},
        skipped_fields=proposed_skipped,
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
    writer.writerow([
        "datum", "kuryr", "trasa", "pocet_hd", "pocet_boxy", "hd_psd_box",
        "svoz_do_50", "svoz_do_100", "svoz_nad_100", "dobirky", "pocet_baliku",
        "nedorucene", "km", "potvrzeno", "poznamka",
    ])
    for e in q:
        writer.writerow([
            e.date, e.user.full_name, e.route.name,
            e.pocet_hd, e.pocet_boxy, e.hd_psd_box,
            e.svoz_do_50, e.svoz_do_100, e.svoz_nad_100, e.dobirky, e.pocet_baliku,
            e.nedorucene, e.km,
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
            avg_km=(sum(e.km or 0 for e in entries) / count) if count else 0,
            avg_pocet_baliku=(sum(e.pocet_baliku or 0 for e in entries) / count) if count else 0,
            entries_count=count,
        ))
    return result
