import os
from datetime import date as date_type

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import Base, engine, SessionLocal
from models import User, UserRole
from auth import hash_password
from routers import auth as auth_router
from routers import fuel as fuel_router
from routers import vacation as vacation_router
from routers import performance as performance_router
from routers import notifications as notifications_router
from routers import checklist as checklist_router
from routers.checklist import run_daily_incomplete_check

Base.metadata.create_all(bind=engine)

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
