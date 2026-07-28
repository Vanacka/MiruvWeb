import os
import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user, require_admin
from models import User, UserRole, FuelEntry, FuelStatus
from schemas import FuelEntryOut, FuelSummaryItem

router = APIRouter(prefix="/fuel", tags=["fuel"])

UPLOAD_DIR = "uploads/receipts"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("", response_model=FuelEntryOut)
async def create_fuel_entry(
    date: date_type = Form(...),
    liters: float = Form(...),
    total_price: float = Form(...),
    license_plate: str = Form(...),
    receipt: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ext = os.path.splitext(receipt.filename)[1] or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(await receipt.read())

    entry = FuelEntry(
        user_id=current_user.id,
        date=date,
        liters=liters,
        total_price=total_price,
        license_plate=license_plate,
        receipt_photo_path=path,
        status=FuelStatus.unpaid,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("", response_model=list[FuelEntryOut])
def list_fuel_entries(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Admin vidí vše, kurýr jen svoje položky."""
    q = db.query(FuelEntry)
    if current_user.role != UserRole.admin:
        q = q.filter(FuelEntry.user_id == current_user.id)
    return q.order_by(FuelEntry.date.desc()).all()


@router.patch("/{entry_id}/status", response_model=FuelEntryOut)
def update_status(
    entry_id: int,
    status: FuelStatus,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    entry = db.query(FuelEntry).filter(FuelEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Položka nenalezena")
    entry.status = status
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/summary", response_model=list[FuelSummaryItem])
def fuel_summary(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Celkový přehled nafty za všechny lidi (pro Mirka)."""
    users = db.query(User).filter(User.role == UserRole.courier).all()
    result = []
    for u in users:
        entries = db.query(FuelEntry).filter(FuelEntry.user_id == u.id).all()
        total_liters = sum(e.liters for e in entries)
        total_price = sum(e.total_price for e in entries)
        unpaid_price = sum(e.total_price for e in entries if e.status == FuelStatus.unpaid)
        result.append(FuelSummaryItem(
            user_id=u.id, full_name=u.full_name,
            total_liters=total_liters, total_price=total_price,
            unpaid_price=unpaid_price,
        ))
    return result
