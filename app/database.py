import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, Float, Date, ForeignKey
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set in environment!")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), default="")

class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    room_number = Column(String(20), nullable=False)
    phone = Column(String(20), default="")
    monthly_rent = Column(Float, default=0.0)
    id_type = Column(String(50), default="Aadhar Card")
    id_number = Column(String(50), default="")
    id_document_path = Column(String(255), nullable=True)
    photo_path = Column(String(255), nullable=True)
    joining_date = Column(Date, nullable=True)
    leaving_date = Column(Date, nullable=True)
    is_active = Column(Integer, default=1)

    members = relationship("FamilyMember", back_populates="tenant", cascade="all, delete-orphan")
    payments = relationship("RentPayment", back_populates="tenant", cascade="all, delete-orphan")
    verifications = relationship("PoliceVerification", back_populates="tenant", cascade="all, delete-orphan")

class FamilyMember(Base):
    __tablename__ = "family_members"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    relation = Column(String(50), nullable=False)
    phone = Column(String(20), default="")
    age = Column(Integer, nullable=True)
    id_type = Column(String(50), default="Aadhar Card")
    id_number = Column(String(50), default="")
    id_document_path = Column(String(255), nullable=True)
    photo_path = Column(String(255), nullable=True)

    tenant = relationship("Tenant", back_populates="members")

class RentPayment(Base):
    __tablename__ = "rent_payments"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    fixed_rent = Column(Float, default=0.0)
    water_bill = Column(Float, default=0.0)
    electricity_bill = Column(Float, default=0.0)
    other_charges = Column(Float, default=0.0)
    total_paid = Column(Float, default=0.0)
    elec_prev_reading = Column(Float, default=0.0)
    elec_curr_reading = Column(Float, default=0.0)
    water_prev_reading = Column(Float, default=0.0)
    water_curr_reading = Column(Float, default=0.0)
    payment_date = Column(Date, nullable=False)
    for_month = Column(String(20), nullable=False)
    payment_mode = Column(String(50), default="UPI")
    status = Column(String(20), default="Pending")  # 'Pending' ya 'Paid'
    notes = Column(String(255), default="")

    tenant = relationship("Tenant", back_populates="payments")

class PoliceVerification(Base):
    __tablename__ = "police_verifications"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    police_station = Column(String(100), nullable=False)
    verification_ref_no = Column(String(100), default="")
    submission_date = Column(Date, nullable=False)
    status = Column(String(50), default="Submitted")
    document_path = Column(String(255), nullable=True)
    remarks = Column(String(255), default="")

    tenant = relationship("Tenant", back_populates="verifications")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
