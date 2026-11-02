import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from dotenv import load_dotenv

from app.database import Base, User, Tenant, FamilyMember, RentPayment, PoliceVerification

load_dotenv()

# LOCAL DATABASE URL (Agar local postgres ka password alag ho toh yahan change karein)
LOCAL_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/rent_db"

# NEON CLOUD DATABASE URL
NEON_DB_URL = os.getenv("DATABASE_URL")

async def migrate_data():
    if not NEON_DB_URL or "neon.tech" not in NEON_DB_URL:
        print("❌ Error: .env file me valid Neon DATABASE_URL nahi mila!")
        return

    print("🚀 Connecting to Local and Neon Databases...")
    local_engine = create_async_engine(LOCAL_DB_URL)
    neon_engine = create_async_engine(NEON_DB_URL)

    LocalSession = async_sessionmaker(local_engine, expire_on_commit=False)
    NeonSession = async_sessionmaker(neon_engine, expire_on_commit=False)

    # Step 1: Ensure Tables exist on Neon
    async with neon_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Neon schema ready.")

    async with LocalSession() as local_db, NeonSession() as neon_db:
        # Migrate Users
        users = (await local_db.execute(select(User))).scalars().all()
        for u in users:
            existing = (await neon_db.execute(select(User).where(User.username == u.username))).scalar_one_or_none()
            if not existing:
                neon_db.add(User(id=u.id, username=u.username, hashed_password=u.hashed_password, full_name=u.full_name))
        await neon_db.commit()
        print(f"✅ Users migrated: {len(users)}")

        # Migrate Tenants
        tenants = (await local_db.execute(select(Tenant))).scalars().all()
        for t in tenants:
            existing = (await neon_db.execute(select(Tenant).where(Tenant.id == t.id))).scalar_one_or_none()
            if not existing:
                neon_db.add(Tenant(
                    id=t.id,
                    name=t.name,
                    room_number=t.room_number,
                    phone=t.phone,
                    monthly_rent=t.monthly_rent,
                    id_type=t.id_type,
                    id_number=t.id_number,
                    id_document_path=t.id_document_path,
                    photo_path=t.photo_path,
                    joining_date=t.joining_date,
                    is_active=t.is_active
                ))
        await neon_db.commit()
        print(f"✅ Tenants migrated: {len(tenants)}")

        # Migrate Family Members
        members = (await local_db.execute(select(FamilyMember))).scalars().all()
        for m in members:
            existing = (await neon_db.execute(select(FamilyMember).where(FamilyMember.id == m.id))).scalar_one_or_none()
            if not existing:
                neon_db.add(FamilyMember(
                    id=m.id,
                    tenant_id=m.tenant_id,
                    name=m.name,
                    relation=m.relation,
                    phone=m.phone,
                    age=m.age,
                    id_type=m.id_type,
                    id_number=m.id_number,
                    id_document_path=m.id_document_path,
                    photo_path=m.photo_path
                ))
        await neon_db.commit()
        print(f"✅ Family Members migrated: {len(members)}")

        # Migrate Rent Payments & Meter Readings
        payments = (await local_db.execute(select(RentPayment))).scalars().all()
        for p in payments:
            existing = (await neon_db.execute(select(RentPayment).where(RentPayment.id == p.id))).scalar_one_or_none()
            if not existing:
                neon_db.add(RentPayment(
                    id=p.id,
                    tenant_id=p.tenant_id,
                    fixed_rent=p.fixed_rent,
                    water_bill=p.water_bill,
                    electricity_bill=p.electricity_bill,
                    other_charges=p.other_charges,
                    total_paid=p.total_paid,
                    elec_prev_reading=p.elec_prev_reading,
                    elec_curr_reading=p.elec_curr_reading,
                    water_prev_reading=p.water_prev_reading,
                    water_curr_reading=p.water_curr_reading,
                    payment_date=p.payment_date,
                    for_month=p.for_month,
                    payment_mode=p.payment_mode,
                    notes=p.notes
                ))
        await neon_db.commit()
        print(f"✅ Rent Payments migrated: {len(payments)}")

        # Migrate Police Verification Records
        verifs = (await local_db.execute(select(PoliceVerification))).scalars().all()
        for v in verifs:
            existing = (await neon_db.execute(select(PoliceVerification).where(PoliceVerification.id == v.id))).scalar_one_or_none()
            if not existing:
                neon_db.add(PoliceVerification(
                    id=v.id,
                    tenant_id=v.tenant_id,
                    police_station=v.police_station,
                    verification_ref_no=v.verification_ref_no,
                    submission_date=v.submission_date,
                    status=v.status,
                    document_path=v.document_path,
                    remarks=v.remarks
                ))
        await neon_db.commit()
        print(f"✅ Police Verifications migrated: {len(verifs)}")

    await local_engine.dispose()
    await neon_engine.dispose()
    print("🎉 ALL LOCAL RECORDS SUCCESSFULLY UPLOADED TO NEON CLOUD!")

if __name__ == "__main__":
    asyncio.run(migrate_data())
