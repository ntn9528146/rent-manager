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

class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    room_number: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=True)
    monthly_rent: Mapped[float] = mapped_column(Float, nullable=False)
    joining_date: Mapped[date] = mapped_column(Date, default=date.today)
    is_active: Mapped[int] = mapped_column(Integer, default=1)

    payments: Mapped[list["RentPayment"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")

class RentPayment(Base):
    __tablename__ = "rent_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    amount_paid: Mapped[float] = mapped_column(Float, nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, default=date.today)
    for_month: Mapped[str] = mapped_column(String(20), nullable=False) # e.g., "Nov 2026"
    payment_mode: Mapped[str] = mapped_column(String(50), default="UPI/Cash")
    notes: Mapped[str] = mapped_column(Text, nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="payments")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
