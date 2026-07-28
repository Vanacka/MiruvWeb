import enum
from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime,
    ForeignKey, Enum, Text, JSON
)
from sqlalchemy.orm import relationship

from database import Base


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


class PerformanceEntry(Base):
    __tablename__ = "performance_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    date = Column(Date, nullable=False)

    # Flexibilní data formuláře - km, počet zásilek, hodiny apod.
    km_driven = Column(Float, default=0)
    packages_delivered = Column(Integer, default=0)
    hours_worked = Column(Float, default=0)
    note = Column(Text, nullable=True)

    # Checkbox potvrzení vyplnění kurýrem
    confirmed = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    user = relationship("User", back_populates="performance_entries", foreign_keys=[user_id])
    route = relationship("Route", back_populates="performance_entries")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    # komu je notifikace určena (typicky Mirkovi/adminovi)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
