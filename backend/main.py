import os
from datetime import date as date_type

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sqlalchemy import inspect, text

from database import Base, engine, SessionLocal
from models import User, UserRole, PerformanceFieldDefinition, PerformanceFieldType
from auth import hash_password
from routers import auth as auth_router
from routers import fuel as fuel_router
from routers import vacation as vacation_router
from routers import performance as performance_router
from routers import notifications as notifications_router
from routers import checklist as checklist_router
from routers.checklist import run_daily_incomplete_check

Base.metadata.create_all(bind=engine)

# create_all jen zakládá chybějící tabulky, ne chybějící sloupce v existujících -
# u SQLite bez Alembicu tak nové sloupce přidáváme ručně, ať se nemusí mazat app.db.
_ENTRY_INT_COLUMNS = [
    "pocet_hd", "pocet_boxy", "hd_psd_box", "svoz_do_50", "svoz_do_100",
    "svoz_nad_100", "dobirky", "pocet_baliku", "nedorucene",
]


def _ensure_columns() -> None:
    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("performance_entry_disputes")}
    if "proposed_skipped_fields" not in existing:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE performance_entry_disputes ADD COLUMN proposed_skipped_fields JSON"
            ))

    entries_existing = {c["name"] for c in inspector.get_columns("performance_entries")}
    disputes_existing = {c["name"] for c in inspector.get_columns("performance_entry_disputes")}
    with engine.begin() as conn:
        for col in _ENTRY_INT_COLUMNS:
            if col not in entries_existing:
                conn.execute(text(f"ALTER TABLE performance_entries ADD COLUMN {col} INTEGER"))
            proposed_col = f"proposed_{col}"
            if proposed_col not in disputes_existing:
                conn.execute(text(
                    f"ALTER TABLE performance_entry_disputes ADD COLUMN {proposed_col} INTEGER"
                ))
        if "km" not in entries_existing:
            conn.execute(text("ALTER TABLE performance_entries ADD COLUMN km FLOAT"))
        if "proposed_km" not in disputes_existing:
            conn.execute(text("ALTER TABLE performance_entry_disputes ADD COLUMN proposed_km FLOAT"))


# Vestavěné sloupce formuláře výkonu (viz _ENTRY_INT_COLUMNS + km výš) dostanou
# vlastní PerformanceFieldDefinition řádek (core=True), aby je šlo skrývat/zobrazovat
# stejným mechanismem jako admin-přidaná vlastní pole. Záporná position drží core pole
# vždy před existujícími vlastními (ta mají position >= 1), ať se nic nepřehází.
_CORE_FIELDS = [
    ("pocet_hd", "Počet HD"),
    ("pocet_boxy", "Počet Boxy"),
    ("hd_psd_box", "HD → PSD/BOX"),
    ("svoz_do_50", "Svoz do 50 ks"),
    ("svoz_do_100", "Svoz do 100 ks"),
    ("svoz_nad_100", "Svoz nad 100 ks"),
    ("dobirky", "Dobírky"),
    ("pocet_baliku", "Počet balíků"),
    ("nedorucene", "Nedoručené"),
    ("km", "Km"),
]


def _ensure_core_performance_fields() -> None:
    inspector = inspect(engine)
    fields_existing = {c["name"] for c in inspector.get_columns("performance_field_definitions")}
    if "core" not in fields_existing:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE performance_field_definitions ADD COLUMN core BOOLEAN NOT NULL DEFAULT 0"
            ))

    db = SessionLocal()
    try:
        existing_keys = {
            key for (key,) in db.query(PerformanceFieldDefinition.key).all()
        }
        for i, (key, label) in enumerate(_CORE_FIELDS):
            if key in existing_keys:
                continue
            db.add(PerformanceFieldDefinition(
                key=key, label=label, field_type=PerformanceFieldType.number,
                required=False, active=True, core=True, position=-100 + i,
            ))
        db.commit()
    finally:
        db.close()


def _ensure_vacation_fields() -> None:
    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("vacation_days")}
    with engine.begin() as conn:
        if "request_group_id" not in existing:
            conn.execute(text("ALTER TABLE vacation_days ADD COLUMN request_group_id INTEGER"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_vacation_days_request_group_id "
            "ON vacation_days(request_group_id)"
        ))
        # Staré řádky (založené po jednom, před zavedením skupin) dostanou samy
        # sebe za group id - skupina o jednom řádku. Po prvním doplnění je sloupec
        # u nových řádků vždy vyplněný, takže se při dalším startu nic nepřepíše.
        conn.execute(text(
            "UPDATE vacation_days SET request_group_id = id WHERE request_group_id IS NULL"
        ))


_ensure_columns()
_ensure_core_performance_fields()
_ensure_vacation_fields()

app = FastAPI(title="MiruvWeb API")

# V dev módu povolíme frontend na localhost:3000.
# V produkci si sem dej doménu, kde frontend reálně běží.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads/receipts", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth_router.router)
app.include_router(fuel_router.router)
app.include_router(vacation_router.router)
app.include_router(performance_router.router)
app.include_router(notifications_router.router)
app.include_router(checklist_router.router)


@app.on_event("startup")
def create_default_admin():
    """Při prvním startu založí admina Mirka, pokud ještě neexistuje.
    Přihlašovací údaje jdou přepsat přes env proměnné ADMIN_USERNAME / ADMIN_PASSWORD.
    """
    db = SessionLocal()
    try:
        username = os.getenv("ADMIN_USERNAME", "mirek")
        if not db.query(User).filter(User.username == username).first():
            password = os.getenv("ADMIN_PASSWORD", "changeme123")
            db.add(User(
                username=username,
                hashed_password=hash_password(password),
                full_name="Mirek",
                role=UserRole.admin,
            ))
            db.commit()
            print(f"[INFO] Vytvořen výchozí admin '{username}' - ZMĚŇ HESLO PO PRVNÍM PŘIHLÁŠENÍ.")
    finally:
        db.close()


scheduler = BackgroundScheduler(timezone=os.getenv("SCHEDULER_TZ", "Europe/Prague"))


def _daily_checklist_job():
    db = SessionLocal()
    try:
        run_daily_incomplete_check(db, date_type.today())
    finally:
        db.close()


@app.on_event("startup")
def start_scheduler():
    """Jednou denně (default 22:00) zkontroluje, kdo nemá hotový checklist,
    a pošle o tom notifikaci adminům. Čas jde přepsat přes CHECKLIST_CHECK_TIME (HH:MM)."""
    hour, minute = (os.getenv("CHECKLIST_CHECK_TIME", "22:00")).split(":")
    scheduler.add_job(
        _daily_checklist_job,
        CronTrigger(hour=int(hour), minute=int(minute)),
        id="daily_checklist_check",
        replace_existing=True,
    )
    scheduler.start()


@app.on_event("shutdown")
def stop_scheduler():
    scheduler.shutdown(wait=False)


@app.get("/")
def root():
    return {"status": "ok"}
