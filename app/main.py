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
from sqlalchemy import select, desc, text, func
from sqlalchemy.orm import selectinload
from jose import JWTError, jwt
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

from app.database import async_session, init_db, engine, User, Tenant, FamilyMember, RentPayment, PoliceVerification
from app.routes.police import router as police_router
from app.routes.whatsapp_billing import router as billing_router

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", "etuvojxj"),
    api_key=os.getenv("CLOUDINARY_API_KEY", "162751417835379"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", "ewtVZLcX1l_qudf3IxkuESPSkdY"),
    secure=True
)

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
app.include_router(billing_router)

def safe_float(val: Optional[str], default: float = 0.0) -> float:
    if val is None:
        return default
    val_str = str(val).strip()
    if not val_str:
        return default
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return default

@app.on_event("startup")
async def on_startup():
    await init_db()
    try:
        async with engine.begin() as conn:
            for tbl in ['family_members', 'tenants', 'rent_payments', 'police_verifications', 'users']:
                await conn.execute(text(f"""
                    SELECT setval(
                        pg_get_serial_sequence('{tbl}', 'id'),
                        (SELECT COALESCE(MAX(id), 0) + 1 FROM {tbl}),
                        false
                    );
                """))
    except Exception as e:
        print(f"Startup sequence sync notice: {e}")

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

async def save_uploaded_file(file: Optional[UploadFile], subfolder: str) -> Optional[str]:
    if not file or not hasattr(file, "filename") or not file.filename or not file.filename.strip():
        return None
    try:
        ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        local_path = os.path.join("uploads", subfolder, unique_filename)
        with open(local_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        if os.getenv("CLOUDINARY_CLOUD_NAME"):
            res = cloudinary.uploader.upload(local_path, folder=f"rent_manager/{subfolder}", resource_type="auto")
            return res.get("secure_url")
        return f"/uploads/{subfolder}/{unique_filename}"
    except Exception as e:
        print(f"File upload warning: {e}")
        return None

# --- AUTH ROUTES ---
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
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Galat Username ya Password!"})

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
        return templates.TemplateResponse(request=request, name="reset_password.html", context={"error": "Dono password match nahi hue!", "msg": None})

    result = await db.execute(select(User).where(User.username == username.strip()))
    user = result.scalar_one_or_none()
    if not user:
        return templates.TemplateResponse(request=request, name="reset_password.html", context={"error": "Yeh username registered nahi hai!", "msg": None})

    user.hashed_password = hash_password(new_password)
    await db.commit()
    return templates.TemplateResponse(request=request, name="reset_password.html", context={"error": None, "msg": "Password kamyabi se update ho gaya! Ab aap login kar sakte hain."})

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
        return templates.TemplateResponse(request=request, name="signup.html", context={"error": "Username pehle se maujood hai!"})

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

# --- DASHBOARD WITH ROOM-BASED LATEST READING LOOKUP ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result_active = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.members), selectinload(Tenant.verifications))
        .where(Tenant.is_active == 1)
        .order_by(Tenant.room_number)
    )
    active_tenants = result_active.scalars().all()

    result_left = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.members), selectinload(Tenant.verifications))
        .where(Tenant.is_active == 0)
        .order_by(desc(Tenant.leaving_date))
    )
    left_tenants = result_left.scalars().all()

    result_payments = await db.execute(
        select(RentPayment)
        .options(selectinload(RentPayment.tenant))
        .order_by(desc(RentPayment.for_month), desc(RentPayment.payment_date), desc(RentPayment.id))
        .limit(100)
    )
    payments = result_payments.scalars().all()

    # Room number ke according sabse latest electricity current reading map karna
    room_last_readings = {}
    for p in payments:
        if p.tenant and p.tenant.room_number:
            rm = p.tenant.room_number.strip()
            if rm not in room_last_readings:
                room_last_readings[rm] = float(p.elec_curr_reading or 0.0)

    # Har active tenant ke sath uske room ki latest reading jodna
    tenant_list_with_readings = []
    for t in active_tenants:
        rm = t.room_number.strip()
        last_rd = room_last_readings.get(rm, 0.0)
        tenant_list_with_readings.append({
            "tenant": t,
            "last_reading": last_rd
        })

    current_month_picker = date.today().strftime("%Y-%m")
    today_date = date.today().strftime("%Y-%m-%d")

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "tenants": active_tenants,
            "tenants_with_readings": tenant_list_with_readings,
            "left_tenants": left_tenants,
            "payments": payments,
            "current_month_picker": current_month_picker,
            "today_date": today_date
        }
    )

# --- TENANT CRUD + LEAVING WORKFLOW ---
@app.post("/tenants/add")
async def add_tenant(
    request: Request,
    name: str = Form(...),
    room_number: str = Form(...),
    phone: Optional[str] = Form(""),
    monthly_rent: Optional[str] = Form("0"),
    id_type: Optional[str] = Form("Aadhar Card"),
    id_number: Optional[str] = Form(""),
    joining_date: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    id_doc: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    photo_path = await save_uploaded_file(photo, "photos")
    doc_path = await save_uploaded_file(id_doc, "documents")
    
    parsed_date = date.today()
    if joining_date and joining_date.strip():
        try:
            parsed_date = datetime.strptime(joining_date.strip(), "%Y-%m-%d").date()
        except Exception:
            parsed_date = date.today()

    tenant = Tenant(
        name=name.strip(),
        room_number=room_number.strip(),
        phone=(phone or "").strip(),
        monthly_rent=safe_float(monthly_rent, 0.0),
        id_type=id_type or "Aadhar Card",
        id_number=(id_number or "").strip(),
        joining_date=parsed_date,
        is_active=1,
        photo_path=photo_path,
        id_document_path=doc_path
    )
    db.add(tenant)
    await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/tenants/{tenant_id}/leave")
async def tenant_leave(
    tenant_id: int,
    request: Request,
    leaving_date: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant:
        l_date = date.today()
        if leaving_date and leaving_date.strip():
            try:
                l_date = datetime.strptime(leaving_date.strip(), "%Y-%m-%d").date()
            except Exception:
                l_date = date.today()
        tenant.is_active = 0
        tenant.leaving_date = l_date
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/tenants/{tenant_id}/restore")
async def tenant_restore(
    tenant_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant:
        tenant.is_active = 1
        tenant.leaving_date = None
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/tenants/{tenant_id}/edit")
async def edit_tenant(
    tenant_id: int,
    request: Request,
    name: str = Form(...),
    room_number: str = Form(...),
    phone: Optional[str] = Form(""),
    monthly_rent: Optional[str] = Form("0"),
    id_type: Optional[str] = Form("Aadhar Card"),
    id_number: Optional[str] = Form(""),
    photo: Optional[UploadFile] = File(None),
    id_doc: Optional[UploadFile] = File(None),
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
        tenant.phone = (phone or "").strip()
        tenant.monthly_rent = safe_float(monthly_rent, 0.0)
        tenant.id_type = id_type or "Aadhar Card"
        tenant.id_number = (id_number or "").strip()
        
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
    phone: Optional[str] = Form(""),
    age: Optional[str] = Form(None),
    id_type: Optional[str] = Form("Aadhar Card"),
    id_number: Optional[str] = Form(""),
    photo: Optional[UploadFile] = File(None),
    id_doc: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    photo_path = await save_uploaded_file(photo, "photos")
    doc_path = await save_uploaded_file(id_doc, "documents")

    parsed_age = None
    if age and str(age).strip().isdigit():
        parsed_age = int(str(age).strip())

    try:
        member = FamilyMember(
            tenant_id=tenant_id,
            name=member_name.strip(),
            relation=relation.strip(),
            phone=(phone or "").strip(),
            age=parsed_age,
            id_type=id_type or "Aadhar Card",
            id_number=(id_number or "").strip(),
            photo_path=photo_path,
            id_document_path=doc_path
        )
        db.add(member)
        await db.commit()
    except Exception:
        await db.rollback()
        max_id_res = await db.execute(select(func.coalesce(func.max(FamilyMember.id), 0)))
        next_id = max_id_res.scalar() + 1
        member = FamilyMember(
            id=next_id,
            tenant_id=tenant_id,
            name=member_name.strip(),
            relation=relation.strip(),
            phone=(phone or "").strip(),
            age=parsed_age,
            id_type=id_type or "Aadhar Card",
            id_number=(id_number or "").strip(),
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
    phone: Optional[str] = Form(""),
    age: Optional[str] = Form(None),
    id_type: Optional[str] = Form("Aadhar Card"),
    id_number: Optional[str] = Form(""),
    photo: Optional[UploadFile] = File(None),
    id_doc: Optional[UploadFile] = File(None),
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
        member.phone = (phone or "").strip()
        if age and str(age).strip().isdigit():
            member.age = int(str(age).strip())
        member.id_type = id_type or "Aadhar Card"
        member.id_number = (id_number or "").strip()
        
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

# --- COMPLETELY BULLETPROOF PAYMENT EDIT & RECORD ---
@app.post("/payments/record")
async def record_payment(
    request: Request,
    tenant_id: int = Form(...),
    fixed_rent: Optional[str] = Form("0"),
    water_bill: Optional[str] = Form("100"),
    electricity_bill: Optional[str] = Form("0"),
    other_charges: Optional[str] = Form("0"),
    elec_prev_reading: Optional[str] = Form("0"),
    elec_curr_reading: Optional[str] = Form("0"),
    water_prev_reading: Optional[str] = Form("0"),
    water_curr_reading: Optional[str] = Form("0"),
    for_month: str = Form(...),
    payment_date: Optional[str] = Form(None),
    payment_mode: str = Form("UPI"),
    notes: Optional[str] = Form(""),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    f_rent = safe_float(fixed_rent, 0.0)
    w_bill = safe_float(water_bill, 100.0)
    e_bill = safe_float(electricity_bill, 0.0)
    o_charges = safe_float(other_charges, 0.0)
    total_amount = f_rent + w_bill + e_bill + o_charges

    pay_dt = date.today()
    if payment_date and payment_date.strip():
        try:
            pay_dt = datetime.strptime(payment_date.strip(), "%Y-%m-%d").date()
        except Exception:
            pay_dt = date.today()

    try:
        payment = RentPayment(
            tenant_id=tenant_id,
            fixed_rent=f_rent,
            water_bill=w_bill,
            electricity_bill=e_bill,
            other_charges=o_charges,
            total_paid=total_amount,
            elec_prev_reading=safe_float(elec_prev_reading, 0.0),
            elec_curr_reading=safe_float(elec_curr_reading, 0.0),
            water_prev_reading=safe_float(water_prev_reading, 0.0),
            water_curr_reading=safe_float(water_curr_reading, 0.0),
            for_month=for_month.strip(),
            payment_date=pay_dt,
            payment_mode=payment_mode.strip() if payment_mode else "UPI",
            status="Pending",
            notes=notes.strip() if notes else ""
        )
        db.add(payment)
        await db.commit()
    except Exception:
        await db.rollback()
        max_id_res = await db.execute(select(func.coalesce(func.max(RentPayment.id), 0)))
        next_id = max_id_res.scalar() + 1
        payment = RentPayment(
            id=next_id,
            tenant_id=tenant_id,
            fixed_rent=f_rent,
            water_bill=w_bill,
            electricity_bill=e_bill,
            other_charges=o_charges,
            total_paid=total_amount,
            elec_prev_reading=safe_float(elec_prev_reading, 0.0),
            elec_curr_reading=safe_float(elec_curr_reading, 0.0),
            water_prev_reading=safe_float(water_prev_reading, 0.0),
            water_curr_reading=safe_float(water_curr_reading, 0.0),
            for_month=for_month.strip(),
            payment_date=pay_dt,
            payment_mode=payment_mode.strip() if payment_mode else "UPI",
            status="Pending",
            notes=notes.strip() if notes else ""
        )
        db.add(payment)
        await db.commit()

    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/payments/{payment_id}/edit")
async def edit_payment(
    payment_id: int,
    request: Request,
    for_month: str = Form(...),
    payment_date: Optional[str] = Form(None),
    fixed_rent: Optional[str] = Form("0"),
    water_bill: Optional[str] = Form("0"),
    electricity_bill: Optional[str] = Form("0"),
    other_charges: Optional[str] = Form("0"),
    elec_prev_reading: Optional[str] = Form("0"),
    elec_curr_reading: Optional[str] = Form("0"),
    water_prev_reading: Optional[str] = Form("0"),
    water_curr_reading: Optional[str] = Form("0"),
    payment_mode: Optional[str] = Form("UPI"),
    notes: Optional[str] = Form(""),
    db: AsyncSession = Depends(get_db)
):
    user = await get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    result = await db.execute(select(RentPayment).where(RentPayment.id == payment_id))
    payment = result.scalar_one_or_none()
    if payment:
        f_rent = safe_float(fixed_rent, 0.0)
        w_bill = safe_float(water_bill, 0.0)
        e_bill = safe_float(electricity_bill, 0.0)
        o_charges = safe_float(other_charges, 0.0)
        
        payment.fixed_rent = f_rent
        payment.water_bill = w_bill
        payment.electricity_bill = e_bill
        payment.other_charges = o_charges
        payment.total_paid = f_rent + w_bill + e_bill + o_charges
        payment.elec_prev_reading = safe_float(elec_prev_reading, 0.0)
        payment.elec_curr_reading = safe_float(elec_curr_reading, 0.0)
        payment.water_prev_reading = safe_float(water_prev_reading, 0.0)
        payment.water_curr_reading = safe_float(water_curr_reading, 0.0)
        payment.for_month = for_month.strip()
        
        if payment_date and payment_date.strip():
            try:
                payment.payment_date = datetime.strptime(payment_date.strip(), "%Y-%m-%d").date()
            except Exception:
                pass
        
        if payment_mode and payment_mode.strip():
            payment.payment_mode = payment_mode.strip()
        if notes is not None:
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
