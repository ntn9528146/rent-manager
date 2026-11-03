import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
from sqlalchemy import select
from app.database import async_session, Tenant, FamilyMember, PoliceVerification

load_dotenv()

cloudinary.config(
    cloud_name="etuvojxj",
    api_key="162751417835379",
    api_secret="ewtVZLcX1l_qudf3IxkuESPSkdY",
    secure=True
)

def upload_local_file(rel_path):
    if not rel_path or rel_path.startswith("http"):
        return rel_path
    
    clean_path = rel_path.lstrip("/").replace("\\", "/")
    if os.path.exists(clean_path):
        try:
            print(f"Uploading {clean_path} ...")
            res = cloudinary.uploader.upload(clean_path, folder="rent_manager/migrated", resource_type="auto")
            return res.get("secure_url")
        except Exception as e:
            print(f"Upload error on {clean_path}: {e}")
    return rel_path

async def sync_existing_files():
    print("🚀 Local storage ki files Cloudinary par sync ho rahi hain...")
    async with async_session() as session:
        # Tenants
        tenants = (await session.execute(select(Tenant))).scalars().all()
        for t in tenants:
            if t.photo_path and not t.photo_path.startswith("http"):
                t.photo_path = upload_local_file(t.photo_path)
            if t.id_document_path and not t.id_document_path.startswith("http"):
                t.id_document_path = upload_local_file(t.id_document_path)
        
        # Family Members
        members = (await session.execute(select(FamilyMember))).scalars().all()
        for m in members:
            if m.photo_path and not m.photo_path.startswith("http"):
                m.photo_path = upload_local_file(m.photo_path)
            if m.id_document_path and not m.id_document_path.startswith("http"):
                m.id_document_path = upload_local_file(m.id_document_path)

        # Police Verifications
        verifs = (await session.execute(select(PoliceVerification))).scalars().all()
        for v in verifs:
            if v.document_path and not v.document_path.startswith("http"):
                v.document_path = upload_local_file(v.document_path)

        await session.commit()
    print("✅ Saari purani files Cloudinary par successfully upload aur Neon database me update ho gayi hain!")

if __name__ == "__main__":
    asyncio.run(sync_existing_files())
