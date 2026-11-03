import urllib.parse
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date

from app.database import async_session, Tenant, RentPayment

router = APIRouter(prefix="/billing", tags=["billing"])

# Updated Default Settings
DEFAULT_WATER_BILL = 100.0
DEFAULT_ELEC_UNIT_RATE = 7.5  # Rate updated to 7.5 per unit
YOUR_UPI_ID = "your_upi_id@upi"
YOUR_NAME = "Nitin Tripathi"

async def get_db():
    async with async_session() as session:
        yield session

@router.post("/generate-bill")
async def generate_bill(
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

    units_consumed = max(0.0, curr_reading - prev_reading)
    elec_bill = round(units_consumed * unit_rate, 2)
    fixed_rent = tenant.monthly_rent
    total_amount = round(fixed_rent + water_bill + elec_bill + other_charges, 2)

    # Dynamic UPI Payment Deep Link
    upi_payment_link = f"upi://pay?pa={YOUR_UPI_ID}&pn={urllib.parse.quote(YOUR_NAME)}&am={total_amount}&cu=INR&tn=Rent-{for_month}"
    qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(upi_payment_link)}"

    msg = (
        f"Namaste {tenant.name} ji,\n"
        f"Aapke Kamra No. {tenant.room_number} ka {for_month} mahine ka rent bill:\n\n"
        f"1. Fixed Rent: Rs. {fixed_rent}\n"
        f"2. Bijli Bill ({prev_reading} se {curr_reading} = {units_consumed} unit @ Rs. {unit_rate}): Rs. {elec_bill}\n"
        f"3. Paani Charges: Rs. {water_bill}\n"
        f"4. Anya Charges: Rs. {other_charges}\n"
        f"----------------------------------\n"
        f"*Kul Rashi (Total Due): Rs. {total_amount}*\n\n"
        f"Kripya niche diye link se direct UPI payment karein ya QR scan karein:\n"
        f"Pay Link: {upi_payment_link}\n"
        f"QR Code: {qr_code_url}\n\n"
        f"Payment karne ke baad screenshot share karein. Dhanyawad!"
    )

    encoded_msg = urllib.parse.quote(msg)
    clean_phone = tenant.phone.strip().replace("+", "").replace("-", "").replace(" ", "") if tenant.phone else ""
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    wa_link = f"https://wa.me/{clean_phone}?text={encoded_msg}"
    return RedirectResponse(url=wa_link, status_code=status.HTTP_303_SEE_OTHER)

@router.post("/quick-mark-paid")
async def quick_mark_paid(
    tenant_id: int = Form(...),
    for_month: str = Form(...),
    fixed_rent: float = Form(0.0),
    water_bill: float = Form(DEFAULT_WATER_BILL),
    electricity_bill: float = Form(0.0),
    other_charges: float = Form(0.0),
    elec_prev_reading: float = Form(0.0),
    elec_curr_reading: float = Form(0.0),
    payment_mode: str = Form("UPI"),
    db: AsyncSession = Depends(get_db)
):
    total_amount = float(fixed_rent) + float(water_bill) + float(electricity_bill) + float(other_charges)
    payment = RentPayment(
        tenant_id=tenant_id,
        fixed_rent=fixed_rent,
        water_bill=water_bill,
        electricity_bill=electricity_bill,
        other_charges=other_charges,
        total_paid=total_amount,
        elec_prev_reading=elec_prev_reading,
        elec_curr_reading=elec_curr_reading,
        water_prev_reading=0.0,
        water_curr_reading=0.0,
        for_month=for_month.strip(),
        payment_date=date.today(),
        payment_mode=payment_mode.strip(),
        notes=f"Quick Marked as {payment_mode}"
    )
    db.add(payment)
    await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
