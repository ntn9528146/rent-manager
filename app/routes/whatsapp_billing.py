import urllib.parse
from datetime import datetime, date
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import async_session, Tenant, RentPayment

router = APIRouter(prefix="/billing", tags=["billing"])

DEFAULT_WATER_BILL = 100.0
DEFAULT_ELEC_UNIT_RATE = 7.5
YOUR_UPI_ID = "7351324716@upi"
YOUR_NAME = "Nitin Tripathi"

async def get_db():
    async with async_session() as session:
        yield session

def format_month_name(month_str: str) -> str:
    try:
        dt = datetime.strptime(month_str.strip(), "%Y-%m")
        return dt.strftime("%B %Y")
    except Exception:
        return month_str

@router.post("/send-whatsapp-bill")
async def send_whatsapp_bill(
    tenant_id: int = Form(...),
    for_month: str = Form(...),
    curr_reading: float = Form(...),
    prev_reading: float = Form(0.0),
    unit_rate: float = Form(DEFAULT_ELEC_UNIT_RATE),
    water_bill: float = Form(DEFAULT_WATER_BILL),
    other_charges: float = Form(0.0),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    units = max(0.0, round(curr_reading - prev_reading, 2))
    elec_amount = round(units * unit_rate, 2)
    fixed_rent = float(tenant.monthly_rent)
    other_amt = float(other_charges) if other_charges else 0.0
    total_due = round(fixed_rent + water_bill + elec_amount + other_amt, 2)

    formatted_month = format_month_name(for_month)

    # 1. AUTO-SAVE RECORD IN DATABASE (With Status = Pending)
    try:
        payment = RentPayment(
            tenant_id=tenant_id,
            fixed_rent=fixed_rent,
            water_bill=water_bill,
            electricity_bill=elec_amount,
            other_charges=other_amt,
            total_paid=total_due,
            elec_prev_reading=prev_reading,
            elec_curr_reading=curr_reading,
            water_prev_reading=0.0,
            water_curr_reading=0.0,
            for_month=for_month.strip(),
            payment_date=date.today(),
            payment_mode="UPI",
            status="Pending",
            notes="Generated via WhatsApp Auto-Bill"
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
            fixed_rent=fixed_rent,
            water_bill=water_bill,
            electricity_bill=elec_amount,
            other_charges=other_amt,
            total_paid=total_due,
            elec_prev_reading=prev_reading,
            elec_curr_reading=curr_reading,
            water_prev_reading=0.0,
            water_curr_reading=0.0,
            for_month=for_month.strip(),
            payment_date=date.today(),
            payment_mode="UPI",
            status="Pending",
            notes="Generated via WhatsApp Auto-Bill"
        )
        db.add(payment)
        await db.commit()

    # 2. UPI Intent URL & Clean Instant QR Code
    upi_url = f"upi://pay?pa={YOUR_UPI_ID}&pn={urllib.parse.quote(YOUR_NAME)}&am={total_due}&cu=INR&tn=Rent-{urllib.parse.quote(formatted_month)}"
    qr_view_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={urllib.parse.quote(upi_url)}"

    msg = (
        f"🏠 *RENT & UTILITY BILL*\n"
        f"----------------------------------\n"
        f"Kirayedar: *{tenant.name}*\n"
        f"Month: *{formatted_month}*\n\n"
        f"1. Fixed Rent: *₹{fixed_rent}*\n"
        f"2. Bijli ({prev_reading} se {curr_reading} = {units} unit @ ₹{unit_rate}): *₹{elec_amount}*\n"
        f"3. Paani Charges (Fixed): *₹{water_bill}*\n"
        f"4. Anya Charges: *₹{other_amt}*\n"
        f"----------------------------------\n"
        f"👉 *KUL RASHI (TOTAL DUE): ₹{total_due}*\n"
        f"----------------------------------\n\n"
        f"📲 *Direct Pay Link (Click to Pay):*\n{upi_url}\n\n"
        f"🖼️ *Scan QR Code to Pay:*\n{qr_view_url}\n\n"
        f"Payment karne ke baad receipt/screenshot share karein. Dhanyawad!"
    )

    clean_phone = tenant.phone.strip().replace("+", "").replace("-", "").replace(" ", "") if tenant.phone else ""
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    encoded_msg = urllib.parse.quote(msg)
    wa_url = f"https://wa.me/{clean_phone}?text={encoded_msg}"
    return RedirectResponse(url=wa_url, status_code=status.HTTP_303_SEE_OTHER)

@router.get("/toggle-status/{payment_id}")
async def toggle_payment_status(payment_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RentPayment).where(RentPayment.id == payment_id))
    payment = result.scalar_one_or_none()
    if payment:
        payment.status = "Paid" if payment.status == "Pending" else "Pending"
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
