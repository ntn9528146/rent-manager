import os
import uuid
import shutil
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, UploadFile, File, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import async_session, PoliceVerification

router = APIRouter(prefix="/police", tags=["police"])

async def get_db():
    async with async_session() as session:
        yield session

async def save_police_file(file: UploadFile) -> Optional[str]:
    if not file or not file.filename:
        return None
    ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join("uploads", "police_docs", unique_filename)
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return f"/uploads/police_docs/{unique_filename}"

@router.post("/add")
async def add_police_verification(
    tenant_id: int = Form(...),
    police_station: str = Form(...),
    verification_ref_no: str = Form(""),
    submission_date: str = Form(None),
    status_val: str = Form("Submitted"),
    remarks: str = Form(""),
    document: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
):
    doc_path = await save_police_file(document)
    sub_date = datetime.strptime(submission_date, "%Y-%m-%d").date() if submission_date else date.today()

    record = PoliceVerification(
        tenant_id=tenant_id,
        police_station=police_station.strip(),
        verification_ref_no=verification_ref_no.strip(),
        submission_date=sub_date,
        status=status_val,
        document_path=doc_path,
        remarks=remarks.strip()
    )
    db.add(record)
    await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/{verification_id}/edit")
async def edit_police_verification(
    verification_id: int,
    police_station: str = Form(...),
    verification_ref_no: str = Form(""),
    submission_date: str = Form(None),
    status_val: str = Form("Submitted"),
    remarks: str = Form(""),
    document: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(PoliceVerification).where(PoliceVerification.id == verification_id))
    rec = result.scalar_one_or_none()
    if rec:
        rec.police_station = police_station.strip()
        rec.verification_ref_no = verification_ref_no.strip()
        if submission_date:
            rec.submission_date = datetime.strptime(submission_date, "%Y-%m-%d").date()
        rec.status = status_val
        rec.remarks = remarks.strip()
        new_doc = await save_police_file(document)
        if new_doc:
            rec.document_path = new_doc
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/{verification_id}/delete")
async def delete_police_verification(verification_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(PoliceVerification).where(PoliceVerification.id == verification_id))
    rec = result.scalar_one_or_none()
    if rec:
        await db.delete(rec)
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
