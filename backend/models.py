import enum
from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime,
    ForeignKey, Enum, Text, JSON, UniqueConstraint, Table
)
from sqlalchemy.orm import relationship

from database import Base

# Preferované trasy kurýra - M:N mezi uživatelem a trasou.
# Prázdný výběr = kurýr zatím nemá nic přiřazeno -> smí (dočasně) vyplňovat kteroukoliv trasu.
user_preferred_routes = Table(
    "user_preferred_routes",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("route_id", Integer, ForeignKey("routes.id"), primary_key=True),
)


class UserRole(str, enum.Enum):
    admin = "admin"      # Mirek
    courier = "courier"  # kurýr


class FuelStatus(str, enum.Enum):
    unpaid = "unpaid"
    paid = "paid"


class VacationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.courier, nullable=False)
    vacation_days_limit = Column(Integer, default=20)
    is_active = Column(Boolean, default=True)

    fuel_entries = relationship("FuelEntry", back_populates="user")
    vacation_days = relationship("VacationDay", back_populates="user")
    performance_entries = relationship(
        "PerformanceEntry",
        back_populates="user",
        foreign_keys="PerformanceEntry.user_id",
    )
    preferred_routes = relationship(
        "Route", secondary=user_preferred_routes, back_populates="preferred_by",
    )


class FuelEntry(Base):
    __tablename__ = "fuel_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    liters = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)
    license_plate = Column(String, nullable=False)
    receipt_photo_path = Column(String, nullable=True)
    status = Column(Enum(FuelStatus), default=FuelStatus.unpaid, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="fuel_entries")


class VacationDay(Base):
    __tablename__ = "vacation_days"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    status = Column(Enum(VacationStatus), default=VacationStatus.pending, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # True pokud den zadal rovnou Mirek (bez schvalovacího procesu)
    created_by_admin = Column(Boolean, default=False)

    user = relationship("User", back_populates="vacation_days")


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)

    performance_entries = relationship("PerformanceEntry", back_populates="route")
    preferred_by = relationship(
        "User", secondary=user_preferred_routes, back_populates="preferred_routes",
    )


class PerformanceEntry(Base):
    __tablename__ = "performance_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    date = Column(Date, nullable=False)

    # Denní výkon - viz PerformanceEntryCreate pro popis jednotlivých polí.
    pocet_hd = Column(Integer, nullable=True)
    pocet_boxy = Column(Integer, nullable=True)
    hd_psd_box = Column(Integer, nullable=True)
    svoz_do_50 = Column(Integer, nullable=True)
    svoz_do_100 = Column(Integer, nullable=True)
    svoz_nad_100 = Column(Integer, nullable=True)
    dobirky = Column(Integer, nullable=True)
    pocet_baliku = Column(Integer, nullable=True)
    nedorucene = Column(Integer, nullable=True)
    km = Column(Float, nullable=True)
    note = Column(Text, nullable=True)

    # Hodnoty vlastních polí, která si admin sám přidal (viz PerformanceFieldDefinition),
    # klíčované podle PerformanceFieldDefinition.key.
    extra_fields = Column(JSON, default=dict)

    # Klíče položek, které kurýr ve wizardu nechal "vyplnit později".
    skipped_fields = Column(JSON, default=list)

    # Odvozeno ze skipped_fields (prázdné = kompletně vyplněno) - nenastavuje se ručně.
    confirmed = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    user = relationship("User", back_populates="performance_entries", foreign_keys=[user_id])
    route = relationship("Route", back_populates="performance_entries")
    edits = relationship(
        "PerformanceEntryEdit", back_populates="entry", order_by="PerformanceEntryEdit.edited_at",
    )


class PerformanceEntryEdit(Base):
    """Log jednotlivých úprav záznamu výkonu - kdo, kdy a co změnil.
    Vytváření záznamu (create_entry) se sem nezaznamenává, jen následné PATCHe."""
    __tablename__ = "performance_entry_edits"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("performance_entries.id"), nullable=False)
    edited_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    edited_at = Column(DateTime, default=datetime.utcnow)
    changes = Column(JSON, default=dict)  # {"pole": {"old": ..., "new": ...}, ...}

    entry = relationship("PerformanceEntry", back_populates="edits")
    edited_by = relationship("User")


class DisputeStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class PerformanceEntryDispute(Base):
    """Nahlášení, že na dané trase/dni je omylem záznam od jiného kurýra.
    Nahlašující kurýr přiloží svoje vlastní údaje pro tu trasu/den, ale nic
    se nezapíše do performance_entries, dokud to neschválí admin - ten zároveň
    rozhodne, na jakou trasu se má přesunout ten původní (chybný) záznam."""
    __tablename__ = "performance_entry_disputes"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    date = Column(Date, nullable=False)
    conflicting_entry_id = Column(Integer, ForeignKey("performance_entries.id"), nullable=False)
    reported_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Údaje, které nahlašující kurýr tvrdí, že patří na tuto trasu/den
    proposed_pocet_hd = Column(Integer, nullable=True)
    proposed_pocet_boxy = Column(Integer, nullable=True)
    proposed_hd_psd_box = Column(Integer, nullable=True)
    proposed_svoz_do_50 = Column(Integer, nullable=True)
    proposed_svoz_do_100 = Column(Integer, nullable=True)
    proposed_svoz_nad_100 = Column(Integer, nullable=True)
    proposed_dobirky = Column(Integer, nullable=True)
    proposed_pocet_baliku = Column(Integer, nullable=True)
    proposed_nedorucene = Column(Integer, nullable=True)
    proposed_km = Column(Float, nullable=True)
    proposed_note = Column(Text, nullable=True)
    proposed_confirmed = Column(Boolean, default=False)
    proposed_extra_fields = Column(JSON, default=dict)
    proposed_skipped_fields = Column(JSON, default=list)

    status = Column(Enum(DisputeStatus), default=DisputeStatus.pending, nullable=False)
    # Trasa, na kterou admin při schválení přesune původní (chybný) záznam
    corrected_route_id = Column(Integer, ForeignKey("routes.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    route = relationship("Route", foreign_keys=[route_id])
    corrected_route = relationship("Route", foreign_keys=[corrected_route_id])
    conflicting_entry = relationship("PerformanceEntry", foreign_keys=[conflicting_entry_id])
    reported_by = relationship("User", foreign_keys=[reported_by_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])


class PerformanceFieldType(str, enum.Enum):
    number = "number"
    text = "text"


class PerformanceFieldDefinition(Base):
    """Vlastní pole formuláře výkonu, která si admin může sám přidávat
    (např. 'počet krabic'), aniž by bylo potřeba měnit kód."""
    __tablename__ = "performance_field_definitions"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    label = Column(String, nullable=False)
    field_type = Column(Enum(PerformanceFieldType), default=PerformanceFieldType.number, nullable=False)
    required = Column(Boolean, default=False)
    position = Column(Integer, default=0)
    active = Column(Boolean, default=True)


class DailyChecklist(Base):
    """Ruční položky denního checklistu kurýra (auto, natankování).
    Položka 'vyplnit formulář' se neukládá zde - dopočítává se z existence
    PerformanceEntry pro daný den, aby ji kurýr nemohl odškrtnout ručně.
    """
    __tablename__ = "daily_checklists"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_daily_checklist_user_date"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    car_checked = Column(Boolean, default=False)
    refueled = Column(Boolean, default=False)
    # Zabraňuje opakovanému upozornění adminů na stejný neúplný den.
    notified_incomplete = Column(Boolean, default=False)

    user = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    # komu je notifikace určena (typicky Mirkovi/adminovi)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
