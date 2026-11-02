import os
import shutil
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from passlib.context import CryptContext
from jose import JWTError, jwt

from app.database import async_session, init_db, User, Tenant, FamilyMember, RentPayment

SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_rent_manager_key_2026")
ALGORITHM = "HS256"
COOKIE_NAME = "rent_access_token"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(title="Rent Manager Pro")
templates = Jinja2Templates(directory="app/templates")

# Mount Uploads directory
os.makedirs("uploads/photos", exist_ok=True)
os.makedirs("uploads/documents", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.on_event("startup")
async def on_startup():
    await init_db()

async def get_db():
    async with async_session() as session:
        yield session

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> Optional[User]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            return None
    except JWTError:
        return None
    
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()

async def save_uploaded_file(file: UploadFile, subfolder: str) -> Optional[str]:
    if not file or not file.filename:
        return None
    ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join("uploads", subfolder, unique_filename)
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return f"/uploads/{subfolder}/{unique_filename}"

# --- AUTH ROUTES ---
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

@app.post("/login")
async def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == username.strip()))
    user = result.scalar_one_or_none()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request, name="login.html", context={"error": "Galat Username ya Password!"}
        )

    token = create_access_token({"sub": user.username})
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key=COOKIE_NAME, value=token, httponly=True, max_age=604800)
    return response

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse(request=request, name="signup.html", context={"error": None})

@app.post("/signup")
async def signup_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == username.strip()))
    if result.scalar_one_or_none():
        return templates.TemplateResponse(
            request=request, name="signup.html", context={"error": "Username pehle se maujood hai!"}
        )

    hashed = pwd_context.hash(password)
    user = User(username=username.strip(), hashed_password=hashed, full_name=full_name.strip())
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response

# --- DASHBOARD & CRUD ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result_tenants = await db.execute(
        select(Tenant).options(selectinload(Tenant.members)).where(Tenant.is_active == 1).order_by(Tenant.room_number)
    )
    tenants = result_tenants.scalars().all()

    result_payments = await db.execute(
        select(RentPayment).options(selectinload(RentPayment.tenant)).order_by(desc(RentPayment.payment_date), desc(RentPayment.id)).limit(20)
    )
    payments = result_payments.scalars().all()

    current_month = date.today().strftime("%b %Y")

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "tenants": tenants,
            "payments": payments,
            "current_month": current_month
        }
    )

@app.post("/tenants/add")
async def add_tenant(
    request: Request,
    name: str = Form(...),
    room_number: str = Form(...),
    phone: str = Form(""),
    monthly_rent: float = Form(0.0),
    id_type: str = Form("Aadhar Card"),
    id_number: str = Form(""),
    photo: UploadFile = File(None),
    id_doc: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    photo_path = await save_uploaded_file(photo, "photos")
    doc_path = await save_uploaded_file(id_doc, "documents")

    tenant = Tenant(
        name=name.strip(),
        room_number=room_number.strip(),
        phone=phone.strip(),
        monthly_rent=monthly_rent,
        id_type=id_type,
        id_number=id_number.strip(),
        photo_path=photo_path,
        id_document_path=doc_path
    )
    db.add(tenant)
    await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/tenants/{tenant_id}/members/add")
async def add_family_member(
    tenant_id: int,
    request: Request,
    member_name: str = Form(...),
    relation: str = Form(...),
    age: Optional[int] = Form(None),
    photo: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    photo_path = await save_uploaded_file(photo, "photos")

    member = FamilyMember(
        tenant_id=tenant_id,
        name=member_name.strip(),
        relation=relation.strip(),
        age=age,
        photo_path=photo_path
    )
    db.add(member)
    await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/payments/record")
async def record_payment(
    request: Request,
    tenant_id: int = Form(...),
    fixed_rent: float = Form(0.0),
    water_bill: float = Form(0.0),
    electricity_bill: float = Form(0.0),
    other_charges: float = Form(0.0),
    for_month: str = Form(...),
    payment_mode: str = Form("UPI"),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    total_amount = float(fixed_rent) + float(water_bill) + float(electricity_bill) + float(other_charges)

    payment = RentPayment(
        tenant_id=tenant_id,
        fixed_rent=fixed_rent,
        water_bill=water_bill,
        electricity_bill=electricity_bill,
        other_charges=other_charges,
        total_paid=total_amount,
        for_month=for_month.strip(),
        payment_mode=payment_mode.strip(),
        notes=notes.strip()
    )
    db.add(payment)
    await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
