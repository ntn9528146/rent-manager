import urllib.parse
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import date

from app.database import async_session, Tenant, RentPayment

router = APIRouter(prefix="/billing", tags=["billing"])

DEFAULT_WATER_BILL = 100.0
DEFAULT_ELEC_UNIT_RATE = 7.5
YOUR_UPI_ID = "9639142185@ybl"  # UPI deep link ID
YOUR_NAME = "Nitin Tripathi"

async def get_db():
    async with async_session() as session:
        yield session

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
    total_due = round(fixed_rent + water_bill + elec_amount + other_charges, 2)

    # Dynamic UPI String
    upi_url = f"upi://pay?pa={YOUR_UPI_ID}&pn={urllib.parse.quote(YOUR_NAME)}&am={total_due}&cu=INR&tn=Rent-{for_month}"
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"

    msg = (
        f"🏠 *RENT & UTILITY BILL*\n"
        f"----------------------------------\n"
        f"Kirayedar: *{tenant.name}*\n"
        f"Kamra No: *{tenant.room_number}*\n"
        f"Month: *{for_month}*\n\n"
        f"1. Fixed Rent: *₹{fixed_rent}*\n"
        f"2. Bijli ({prev_reading} se {curr_reading} = {units} unit @ ₹{unit_rate}): *₹{elec_amount}*\n"
        f"3. Paani Charges (Fixed): *₹{water_bill}*\n"
        f"4. Anya Charges: *₹{other_charges}*\n"
        f"----------------------------------\n"
        f"👉 *KUL RASHI (TOTAL DUE): ₹{total_due}*\n"
        f"----------------------------------\n\n"
        f"📲 *Direct Pay Link (Click to Pay):*\n{upi_url}\n\n"
        f"🖼️ *Scan QR Code to Pay:*\n{qr_image_url}\n\n"
        f"Payment karne ke baad receipt/screenshot isi number par bhej dein. Dhanyawad!"
    )

    clean_phone = tenant.phone.strip().replace("+", "").replace("-", "").replace(" ", "") if tenant.phone else ""
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    encoded_msg = urllib.parse.quote(msg)
    wa_url = f"https://wa.me/{clean_phone}?text={encoded_msg}"
    return RedirectResponse(url=wa_url, status_code=status.HTTP_303_SEE_OTHER)
