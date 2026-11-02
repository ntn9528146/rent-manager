import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Float, Date, ForeignKey, Text
from datetime import date
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost:5432/rent_db")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=True)

class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    room_number: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    monthly_rent: Mapped[float] = mapped_column(Float, default=0.0)
    
    id_type: Mapped[str] = mapped_column(String(50), default="Aadhar Card")
    id_number: Mapped[str] = mapped_column(String(50), nullable=True)
    id_document_path: Mapped[str] = mapped_column(String(255), nullable=True)
    photo_path: Mapped[str] = mapped_column(String(255), nullable=True)
    
    joining_date: Mapped[date] = mapped_column(Date, default=date.today)
    is_active: Mapped[int] = mapped_column(Integer, default=1)

    members: Mapped[list["FamilyMember"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    payments: Mapped[list["RentPayment"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    verifications: Mapped[list["PoliceVerification"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")

class FamilyMember(Base):
    __tablename__ = "family_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    relation: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    age: Mapped[int] = mapped_column(Integer, nullable=True)
    id_type: Mapped[str] = mapped_column(String(50), default="Aadhar Card")
    id_number: Mapped[str] = mapped_column(String(50), nullable=True)
    id_document_path: Mapped[str] = mapped_column(String(255), nullable=True)
    photo_path: Mapped[str] = mapped_column(String(255), nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="members")

class PoliceVerification(Base):
    __tablename__ = "police_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    police_station: Mapped[str] = mapped_column(String(100), nullable=False)
    verification_ref_no: Mapped[str] = mapped_column(String(100), nullable=True)
    submission_date: Mapped[date] = mapped_column(Date, default=date.today)
    status: Mapped[str] = mapped_column(String(50), default="Submitted") # Submitted / In Progress / Verified
    document_path: Mapped[str] = mapped_column(String(255), nullable=True)
    remarks: Mapped[str] = mapped_column(Text, nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="verifications")

class RentPayment(Base):
    __tablename__ = "rent_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    
    fixed_rent: Mapped[float] = mapped_column(Float, default=0.0)
    water_bill: Mapped[float] = mapped_column(Float, default=0.0)
    electricity_bill: Mapped[float] = mapped_column(Float, default=0.0)
    other_charges: Mapped[float] = mapped_column(Float, default=0.0)
    total_paid: Mapped[float] = mapped_column(Float, default=0.0)

    elec_prev_reading: Mapped[float] = mapped_column(Float, default=0.0)
    elec_curr_reading: Mapped[float] = mapped_column(Float, default=0.0)
    water_prev_reading: Mapped[float] = mapped_column(Float, default=0.0)
    water_curr_reading: Mapped[float] = mapped_column(Float, default=0.0)

    payment_date: Mapped[date] = mapped_column(Date, default=date.today)
    for_month: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_mode: Mapped[str] = mapped_column(String(50), default="UPI")
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="payments")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
