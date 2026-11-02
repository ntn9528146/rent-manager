import os
import shutil
import uuid
import bcrypt
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from jose import JWTError, jwt

from app.database import async_session, init_db, User, Tenant, FamilyMember, RentPayment, PoliceVerification
from app.routes.police import router as police_router

SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_rent_manager_key_2026")
ALGORITHM = "HS256"
COOKIE_NAME = "rent_access_token"

app = FastAPI(title="Rent Manager Pro")
templates = Jinja2Templates(directory="app/templates")

os.makedirs("uploads/photos", exist_ok=True)
os.makedirs("uploads/documents", exist_ok=True)
os.makedirs("uploads/police_docs", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(police_router)

@app.on_event("startup")
async def on_startup():
    await init_db()

async def get_db():
    async with async_session() as session:
        yield session

def hash_password(password: str) -> str:
    pwd_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode('utf-8')[:72]
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode('utf-8'))

def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
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

# --- AUTH & PASSWORD RESET ROUTES ---
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

@app.post("/login")
async def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember_me: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == username.strip()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request, name="login.html", context={"error": "Galat Username ya Password!"}
        )

    token_expiry = timedelta(days=30) if remember_me else timedelta(days=1)
    cookie_max_age = (30 * 24 * 3600) if remember_me else (24 * 3600)

    token = create_access_token({"sub": user.username}, expires_delta=token_expiry)
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key=COOKIE_NAME, value=token, httponly=True, max_age=cookie_max_age)
    return response

@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="reset_password.html", context={"error": None, "msg": None})

@app.post("/reset-password")
async def reset_password_action(
    request: Request,
    username: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request=request, name="reset_password.html", context={"error": "Dono password match nahi hue!", "msg": None}
        )

    result = await db.execute(select(User).where(User.username == username.strip()))
    user = result.scalar_one_or_none()
    if not user:
        return templates.TemplateResponse(
            request=request, name="reset_password.html", context={"error": "Yeh username registered nahi hai!", "msg": None}
        )

    user.hashed_password = hash_password(new_password)
    await db.commit()
    return templates.TemplateResponse(
        request=request, name="reset_password.html", context={"error": None, "msg": "Password kamyabi se update ho gaya! Ab aap login kar sakte hain."}
    )

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

    hashed = hash_password(password)
    user = User(username=username.strip(), hashed_password=hashed, full_name=full_name.strip())
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response

# --- DASHBOARD & CRUD ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result_tenants = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.members), selectinload(Tenant.verifications))
        .where(Tenant.is_active == 1)
        .order_by(Tenant.room_number)
    )
    tenants = result_tenants.scalars().all()

    result_payments = await db.execute(
        select(RentPayment).options(selectinload(RentPayment.tenant)).order_by(desc(RentPayment.for_month), desc(RentPayment.payment_date)).limit(50)
    )
    payments = result_payments.scalars().all()

    current_month_picker = date.today().strftime("%Y-%m")
    today_date = date.today().strftime("%Y-%m-%d")

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "tenants": tenants,
            "payments": payments,
            "current_month_picker": current_month_picker,
            "today_date": today_date
        }
    )

# --- TENANT CRUD ---
@app.post("/tenants/add")
async def add_tenant(
    request: Request,
    name: str = Form(...),
    room_number: str = Form(...),
    phone: str = Form(""),
    monthly_rent: float = Form(0.0),
    id_type: str = Form("Aadhar Card"),
    id_number: str = Form(""),
    joining_date: str = Form(None),
    photo: UploadFile = File(None),
    id_doc: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    photo_path = await save_uploaded_file(photo, "photos")
    doc_path = await save_uploaded_file(id_doc, "documents")
    parsed_date = datetime.strptime(joining_date, "%Y-%m-%d").date() if joining_date else date.today()

    tenant = Tenant(
        name=name.strip(),
        room_number=room_number.strip(),
        phone=phone.strip(),
        monthly_rent=monthly_rent,
        id_type=id_type,
        id_number=id_number.strip(),
        joining_date=parsed_date,
        photo_path=photo_path,
        id_document_path=doc_path
    )
    db.add(tenant)
    await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/tenants/{tenant_id}/edit")
async def edit_tenant(
    tenant_id: int,
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

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant:
        tenant.name = name.strip()
        tenant.room_number = room_number.strip()
        tenant.phone = phone.strip()
        tenant.monthly_rent = monthly_rent
        tenant.id_type = id_type
        tenant.id_number = id_number.strip()
        new_photo = await save_uploaded_file(photo, "photos")
        if new_photo:
            tenant.photo_path = new_photo
        new_doc = await save_uploaded_file(id_doc, "documents")
        if new_doc:
            tenant.id_document_path = new_doc
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/tenants/{tenant_id}/delete")
async def delete_tenant(tenant_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant:
        await db.delete(tenant)
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

# --- FAMILY MEMBER CRUD ---
@app.post("/tenants/{tenant_id}/members/add")
async def add_family_member(
    tenant_id: int,
    request: Request,
    member_name: str = Form(...),
    relation: str = Form(...),
    phone: str = Form(""),
    age: Optional[int] = Form(None),
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

    member = FamilyMember(
        tenant_id=tenant_id,
        name=member_name.strip(),
        relation=relation.strip(),
        phone=phone.strip(),
        age=age,
        id_type=id_type,
        id_number=id_number.strip(),
        photo_path=photo_path,
        id_document_path=doc_path
    )
    db.add(member)
    await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/members/{member_id}/edit")
async def edit_family_member(
    member_id: int,
    request: Request,
    member_name: str = Form(...),
    relation: str = Form(...),
    phone: str = Form(""),
    age: Optional[int] = Form(None),
    id_type: str = Form("Aadhar Card"),
    id_number: str = Form(""),
    photo: UploadFile = File(None),
    id_doc: UploadFile = File(None),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result = await db.execute(select(FamilyMember).where(FamilyMember.id == member_id))
    member = result.scalar_one_or_none()
    if member:
        member.name = member_name.strip()
        member.relation = relation.strip()
        member.phone = phone.strip()
        member.age = age
        member.id_type = id_type
        member.id_number = id_number.strip()
        new_photo = await save_uploaded_file(photo, "photos")
        if new_photo:
            member.photo_path = new_photo
        new_doc = await save_uploaded_file(id_doc, "documents")
        if new_doc:
            member.id_document_path = new_doc
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/members/{member_id}/delete")
async def delete_family_member(member_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result = await db.execute(select(FamilyMember).where(FamilyMember.id == member_id))
    member = result.scalar_one_or_none()
    if member:
        await db.delete(member)
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

# --- PAYMENT CRUD ---
@app.post("/payments/record")
async def record_payment(
    request: Request,
    tenant_id: int = Form(...),
    fixed_rent: float = Form(0.0),
    water_bill: float = Form(0.0),
    electricity_bill: float = Form(0.0),
    other_charges: float = Form(0.0),
    elec_prev_reading: float = Form(0.0),
    elec_curr_reading: float = Form(0.0),
    water_prev_reading: float = Form(0.0),
    water_curr_reading: float = Form(0.0),
    for_month: str = Form(...),
    payment_date: str = Form(None),
    payment_mode: str = Form("UPI"),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    total_amount = float(fixed_rent) + float(water_bill) + float(electricity_bill) + float(other_charges)
    pay_dt = datetime.strptime(payment_date, "%Y-%m-%d").date() if payment_date else date.today()

    payment = RentPayment(
        tenant_id=tenant_id,
        fixed_rent=fixed_rent,
        water_bill=water_bill,
        electricity_bill=electricity_bill,
        other_charges=other_charges,
        total_paid=total_amount,
        elec_prev_reading=elec_prev_reading,
        elec_curr_reading=elec_curr_reading,
        water_prev_reading=water_prev_reading,
        water_curr_reading=water_curr_reading,
        for_month=for_month.strip(),
        payment_date=pay_dt,
        payment_mode=payment_mode.strip(),
        notes=notes.strip()
    )
    db.add(payment)
    await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/payments/{payment_id}/edit")
async def edit_payment(
    payment_id: int,
    request: Request,
    fixed_rent: float = Form(0.0),
    water_bill: float = Form(0.0),
    electricity_bill: float = Form(0.0),
    other_charges: float = Form(0.0),
    elec_prev_reading: float = Form(0.0),
    elec_curr_reading: float = Form(0.0),
    water_prev_reading: float = Form(0.0),
    water_curr_reading: float = Form(0.0),
    for_month: str = Form(...),
    payment_date: str = Form(None),
    payment_mode: str = Form("UPI"),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result = await db.execute(select(RentPayment).where(RentPayment.id == payment_id))
    payment = result.scalar_one_or_none()
    if payment:
        payment.fixed_rent = fixed_rent
        payment.water_bill = water_bill
        payment.electricity_bill = electricity_bill
        payment.other_charges = other_charges
        payment.total_paid = float(fixed_rent) + float(water_bill) + float(electricity_bill) + float(other_charges)
        payment.elec_prev_reading = elec_prev_reading
        payment.elec_curr_reading = elec_curr_reading
        payment.water_prev_reading = water_prev_reading
        payment.water_curr_reading = water_curr_reading
        payment.for_month = for_month.strip()
        if payment_date:
            payment.payment_date = datetime.strptime(payment_date, "%Y-%m-%d").date()
        payment.payment_mode = payment_mode.strip()
        payment.notes = notes.strip()
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/payments/{payment_id}/delete")
async def delete_payment(payment_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result = await db.execute(select(RentPayment).where(RentPayment.id == payment_id))
    payment = result.scalar_one_or_none()
    if payment:
        await db.delete(payment)
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
