from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from database import get_db
from auth import authenticate_user, create_access_token, get_current_user, require_admin, hash_password
from models import User
from schemas import Token, UserOut, UserCreate, UserActiveUpdate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nesprávné jméno nebo heslo",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tento účet byl deaktivován",
        )
    token = create_access_token({"sub": user.username})
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/users", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Mirek zakládá nové kurýry (nebo dalšího admina)."""
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(400, "Uživatelské jméno už existuje")
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        vacation_days_limit=payload.vacation_days_limit,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).all()


@router.patch("/users/{user_id}/active", response_model=UserOut)
def set_user_active(
    user_id: int,
    payload: UserActiveUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """"Smazání" účtu = deaktivace - přihlášení přestane fungovat a zmizí z výběru
    pro nové akce, ale historie (nafta, dovolená, výkon, spory) zůstává zachovaná
    a admin se k ní pořád dostane. Jde to i vrátit zpět."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Uživatel nenalezen")
    if not payload.is_active and user.id == current_user.id:
        raise HTTPException(400, "Nemůžeš deaktivovat sám sebe")
    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return user
