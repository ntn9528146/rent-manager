import urllib.parse
from datetime import datetime, date
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.database import async_session, Tenant, RentPayment

router = APIRouter(prefix="/billing", tags=["billing"])

DEFAULT_WATER_PER_MONTH = 100.0
DEFAULT_ELEC_UNIT_RATE = 7.5
YOUR_UPI_ID = "7351324716@upi"
YOUR_NAME = "Nitin Tripathi"

async def get_db():
    async with async_session() as session:
        yield session

def format_month_label(m_str: str) -> str:
    try:
        dt = datetime.strptime(m_str.strip(), "%Y-%m")
        return dt.strftime("%B %Y")
    except Exception:
        return m_str

@router.post("/send-whatsapp-bill")
async def send_whatsapp_bill(
    tenant_id: int = Form(...),
    selected_months: List[str] = Form(...),
    curr_reading: float = Form(...),
    prev_reading: float = Form(0.0),
    unit_rate: float = Form(DEFAULT_ELEC_UNIT_RATE),
    water_bill: float = Form(DEFAULT_WATER_PER_MONTH),
    other_type: str = Form("Other"),
    other_custom_name: str = Form(""),
    other_charges: float = Form(0.0),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    month_count = max(1, len(selected_months))
    formatted_months_list = [format_month_label(m) for m in selected_months]
    months_display_str = ", ".join(formatted_months_list)

    units = max(0.0, round(curr_reading - prev_reading, 2))
    elec_amount = round(units * unit_rate, 2)
    single_rent = float(tenant.monthly_rent)
    total_fixed_rent = round(single_rent * month_count, 2)
    total_water = round(DEFAULT_WATER_PER_MONTH * month_count, 2)
    other_amt = float(other_charges) if other_charges else 0.0
    total_due = round(total_fixed_rent + total_water + elec_amount + other_amt, 2)

    # 4. Other Label decide karein
    if other_type == "Water Tanker":
        other_label = "Water Tanker"
    else:
        other_label = other_custom_name.strip() if other_custom_name.strip() else "Other Charges"

    # Auto Save to DB
    notes_val = f"Bill ({months_display_str})"
    if other_amt > 0:
        notes_val += f" | {other_label}: Rs.{other_amt}"

    try:
        payment = RentPayment(
            tenant_id=tenant_id,
            fixed_rent=total_fixed_rent,
            water_bill=total_water,
            electricity_bill=elec_amount,
            other_charges=other_amt,
            total_paid=total_due,
            elec_prev_reading=prev_reading,
            elec_curr_reading=curr_reading,
            water_prev_reading=0.0,
            water_curr_reading=0.0,
            for_month=months_display_str[:20],
            payment_date=date.today(),
            payment_mode="Pending",
            status="Pending",
            notes=notes_val
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
            fixed_rent=total_fixed_rent,
            water_bill=total_water,
            electricity_bill=elec_amount,
            other_charges=other_amt,
            total_paid=total_due,
            elec_prev_reading=prev_reading,
            elec_curr_reading=curr_reading,
            water_prev_reading=0.0,
            water_curr_reading=0.0,
            for_month=months_display_str[:20],
            payment_date=date.today(),
            payment_mode="Pending",
            status="Pending",
            notes=notes_val
        )
        db.add(payment)
        await db.commit()

    # Dynamic Payment Links
    upi_url = f"upi://pay?pa={YOUR_UPI_ID}&pn={urllib.parse.quote(YOUR_NAME)}&am={total_due}&cu=INR&tn=Rent-{urllib.parse.quote(formatted_months_list[0])}"
    qr_view_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={urllib.parse.quote(upi_url)}"

    # Option 1 Casual + Namashkar format
    msg = (
        f"Namashkar {tenant.name} ji 🙏\n\n"
        f"Aapke is baar ke rent aur utility bill ka hisaab niche share kar raha hoon:\n\n"
        f"📅 *Mahina:* {months_display_str}\n"
        f"----------------------------------\n"
        f"1. Fixed Rent: *₹{total_fixed_rent}*\n"
        f"2. Bijli Bill (Last: {prev_reading} se Curr: {curr_reading} | {units} unit): *₹{elec_amount}*\n"
        f"3. Paani Charges: *₹{total_water}*\n"
        f"4. {other_label}: *₹{other_amt}*\n"
        f"----------------------------------\n"
        f"👉 *Kul Rashi (Total Due): ₹{total_due}*\n"
        f"----------------------------------\n\n"
        f"📲 *Direct UPI Pay Link:*\n{upi_url}\n\n"
        f"🖼️ *Scan QR Code:*\n{qr_view_url}\n\n"
        f"Payment hone ke baad screenshot isi number par bhej dijiyega. Dhanyawad!"
    )

    clean_phone = tenant.phone.strip().replace("+", "").replace("-", "").replace(" ", "") if tenant.phone else ""
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    encoded_msg = urllib.parse.quote(msg)
    wa_url = f"https://wa.me/{clean_phone}?text={encoded_msg}"
    return RedirectResponse(url=wa_url, status_code=status.HTTP_303_SEE_OTHER)

@router.post("/update-payment-status")
async def update_payment_status(
    payment_id: int = Form(...),
    pay_status: str = Form(...),
    cash_receiver: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(RentPayment).where(RentPayment.id == payment_id))
    payment = result.scalar_one_or_none()
    if payment:
        payment.status = pay_status
        if pay_status == "Cash Paid":
            payment.payment_mode = "Cash"
            if cash_receiver.strip():
                payment.notes = f"Cash given to: {cash_receiver.strip()}"
        elif pay_status == "Online Paid":
            payment.payment_mode = "Online / UPI"
        else:
            payment.payment_mode = "Pending"
        await db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
