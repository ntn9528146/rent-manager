from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.database import async_session, init_db, Tenant, RentPayment
from contextlib import asynccontextmanager
from datetime import date

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Rent Manager", lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")

async def get_db():
    async with async_session() as session:
        yield session

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    result_tenants = await db.execute(select(Tenant).where(Tenant.is_active == 1).order_by(Tenant.room_number))
    tenants = result_tenants.scalars().all()

    result_payments = await db.execute(
        select(RentPayment).order_by(desc(RentPayment.payment_date), desc(RentPayment.id)).limit(15)
    )
    payments = result_payments.scalars().all()

    current_month = date.today().strftime("%b %Y")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "tenants": tenants,
            "payments": payments,
            "current_month": current_month
        }
    )

@app.post("/tenants/add")
async def add_tenant(
    name: str = Form(...),
    room_number: str = Form(...),
    phone: str = Form(""),
    monthly_rent: float = Form(...),
    db: AsyncSession = Depends(get_db)
):
    new_tenant = Tenant(
        name=name.strip(),
        room_number=room_number.strip(),
        phone=phone.strip(),
        monthly_rent=monthly_rent
    )
    db.add(new_tenant)
    await db.commit()
    return RedirectResponse(url="/", status_code=303)

@app.post("/payments/record")
async def record_payment(
    tenant_id: int = Form(...),
    amount_paid: float = Form(...),
    for_month: str = Form(...),
    payment_mode: str = Form("UPI"),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    payment = RentPayment(
        tenant_id=tenant_id,
        amount_paid=amount_paid,
        for_month=for_month.strip(),
        payment_mode=payment_mode.strip(),
        notes=notes.strip()
    )
    db.add(payment)
    await db.commit()
    return RedirectResponse(url="/", status_code=303)
