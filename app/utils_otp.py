import os
import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def generate_otp() -> str:
    return str(random.randint(100000, 999999))

def send_otp_email(to_email: str, otp: str) -> bool:
    smtp_email = os.getenv("SMTP_EMAIL", "ntn9528146@gmail.com")
    smtp_pass = os.getenv("SMTP_APP_PASSWORD", "rimnaosdpbggdwkj")

    try:
        msg = MIMEMultipart()
        msg['From'] = f"Rent Manager Security <{smtp_email}>"
        msg['To'] = to_email
        msg['Subject'] = f"{otp} is your Rent Manager Password Reset OTP"

        body = f"""Namaste,

Rent Manager portal me password reset karne ke liye aapka One Time Password (OTP) hai:

👉 {otp} 👈

Yeh OTP agle 10 minute tak valid hai. Kripya ise kisi ke sath share na karein.

Security Team,
Rent & Property Manager
"""
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_email.strip(), smtp_pass.replace(" ", "").strip())
        server.send_message(msg)
        server.quit()
        print(f"✅ OTP successfully sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Error sending email via SMTP: {e}")
        return False
