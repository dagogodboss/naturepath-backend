"""
Email Service - Resend Integration
"""
import os
import asyncio
import base64
import html
import logging
import smtplib
from urllib.parse import urlparse

import resend
from typing import Optional, Dict, Any, List
from email.message import EmailMessage
from core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Email service using Resend"""
    
    def __init__(self):
        self.api_key = settings.resend_api_key
        self.sender_email = settings.sender_email
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_username = settings.smtp_username
        self.smtp_password = settings.smtp_password
        self.smtp_use_tls = settings.smtp_use_tls
        self.smtp_sender_email = settings.smtp_sender_email or self.sender_email
        if self.api_key:
            resend.api_key = self.api_key
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        attachments: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Send an email using Resend or SMTP.

        attachments: optional list of {"filename": str, "content_base64": str} (Resend format).
        """
        if self.api_key and self.api_key != "re_placeholder":
            params: Dict[str, Any] = {
                "from": self.sender_email,
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            }

            if text_content:
                params["text"] = text_content
            if attachments:
                params["attachments"] = [
                    {"filename": a["filename"], "content": a["content_base64"]}
                    for a in attachments
                ]

            try:
                email = await asyncio.to_thread(resend.Emails.send, params)
                logger.info(f"Email sent via Resend to {to_email}: {subject}")
                return {
                    "success": True,
                    "provider": "resend",
                    "email_id": email.get("id"),
                    "message": f"Email sent to {to_email}",
                }
            except Exception as e:
                logger.error(f"Failed to send email via Resend: {str(e)}")
                return {"success": False, "provider": "resend", "message": str(e)}

        if self.smtp_host:
            try:
                await asyncio.to_thread(
                    self._send_via_smtp,
                    to_email,
                    subject,
                    html_content,
                    text_content,
                    attachments,
                )
                logger.info(f"Email sent via SMTP to {to_email}: {subject}")
                return {
                    "success": True,
                    "provider": "smtp",
                    "message": f"Email sent to {to_email}",
                }
            except Exception as e:
                logger.error(f"Failed to send email via SMTP: {str(e)}")
                return {"success": False, "provider": "smtp", "message": str(e)}

        logger.warning("No email provider configured (Resend/SMTP) - email not sent")
        return {"success": False, "message": "Email service not configured", "mock": True}

    def _send_via_smtp(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        attachments: Optional[List[Dict[str, str]]] = None,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp_sender_email
        msg["To"] = to_email
        msg.set_content(text_content or "Please view this email in an HTML-compatible client.")
        msg.add_alternative(html_content, subtype="html")
        if attachments:
            for a in attachments:
                raw = base64.standard_b64decode(a["content_base64"])
                msg.add_attachment(
                    raw,
                    maintype="text",
                    subtype="calendar",
                    filename=a["filename"],
                )

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as server:
            if self.smtp_use_tls:
                server.starttls()
            if self.smtp_username and self.smtp_password:
                server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)
    
    async def send_booking_confirmation(
        self,
        to_email: str,
        customer_name: str,
        service_name: str,
        practitioner_name: str,
        date: str,
        time: str,
        booking_id: str,
        *,
        pay_at_counter: bool = True,
        google_calendar_url: Optional[str] = None,
        outlook_live_url: Optional[str] = None,
        outlook_office_url: Optional[str] = None,
        ics_base64: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send booking confirmation email with optional calendar links and .ics attachment."""
        subject = "Booking Confirmed - The Natural Path Spa"
        payment_line = (
            "<p><strong>Payment:</strong> Due at the front desk when you arrive (we do not charge your card online for appointments).</p>"
            if pay_at_counter
            else "<p><strong>Payment:</strong> Your payment was processed.</p>"
        )
        calendar_block = ""
        if google_calendar_url or outlook_live_url or outlook_office_url:
            links = []
            if google_calendar_url:
                links.append(
                    f'<a class="btn" href="{google_calendar_url}" target="_blank" rel="noopener">Add to Google Calendar</a>'
                )
            if outlook_live_url:
                links.append(
                    f'<a class="btn secondary" href="{outlook_live_url}" target="_blank" rel="noopener">Add to Outlook (personal)</a>'
                )
            if outlook_office_url:
                links.append(
                    f'<a class="btn secondary" href="{outlook_office_url}" target="_blank" rel="noopener">Add to Outlook (Microsoft 365)</a>'
                )
            calendar_block = f"""
                    <p style="margin-top:20px;"><strong>Add to your calendar</strong></p>
                    <p style="font-size:13px;color:#555;">Open a link below or use the attached .ics file (Apple Calendar, Google, Outlook).</p>
                    <div style="display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;">{"".join(links)}</div>
            """
        attach_note = (
            "<p style=\"font-size:12px;color:#777;\">A calendar invite is attached as <code>appointment.ics</code>.</p>"
            if ics_base64
            else ""
        )
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #4a7c59 0%, #6b8f71 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .details {{ background: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                .detail-row {{ display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #eee; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
                .btn {{ display: inline-block; background: #4a7c59; color: white !important; padding: 12px 18px; text-decoration: none; border-radius: 5px; font-size: 14px; }}
                .btn.secondary {{ background: #5a6b8c; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>The Natural Path</h1>
                    <p>Your Wellness Journey Awaits</p>
                </div>
                <div class="content">
                    <h2>Hello {customer_name},</h2>
                    <p>Your booking has been confirmed! We look forward to seeing you.</p>
                    {payment_line}
                    <div class="details">
                        <div class="detail-row">
                            <strong>Booking ID:</strong>
                            <span>{booking_id[:8].upper()}</span>
                        </div>
                        <div class="detail-row">
                            <strong>Service:</strong>
                            <span>{service_name}</span>
                        </div>
                        <div class="detail-row">
                            <strong>Practitioner:</strong>
                            <span>{practitioner_name}</span>
                        </div>
                        <div class="detail-row">
                            <strong>Date:</strong>
                            <span>{date}</span>
                        </div>
                        <div class="detail-row">
                            <strong>Time:</strong>
                            <span>{time}</span>
                        </div>
                    </div>
                    {calendar_block}
                    {attach_note}
                    <p>Please arrive 10-15 minutes before your appointment.</p>
                </div>
                <div class="footer">
                    <p>The Natural Path Spa | thenaturalpathla.com</p>
                    <p>If you need to reschedule or cancel, please contact us at least 24 hours in advance.</p>
                </div>
            </div>
        </body>
        </html>
        """
        attachments = None
        if ics_base64:
            attachments = [{"filename": "appointment.ics", "content_base64": ics_base64}]
        return await self.send_email(to_email, subject, html_content, attachments=attachments)

    async def send_practitioner_booking_notice(
        self,
        to_email: str,
        practitioner_first_name: str,
        customer_name: str,
        service_name: str,
        date: str,
        time: str,
        booking_id: str,
        *,
        google_calendar_url: Optional[str] = None,
        outlook_live_url: Optional[str] = None,
        outlook_office_url: Optional[str] = None,
        ics_base64: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Notify practitioner of a new confirmed booking (same calendar helpers as customer)."""
        subject = f"New appointment: {service_name} — {date} {time}"
        calendar_block = ""
        if google_calendar_url or outlook_live_url or outlook_office_url:
            links = []
            if google_calendar_url:
                links.append(
                    f'<a class="btn" href="{google_calendar_url}" target="_blank" rel="noopener">Google Calendar</a>'
                )
            if outlook_live_url:
                links.append(
                    f'<a class="btn secondary" href="{outlook_live_url}" target="_blank" rel="noopener">Outlook</a>'
                )
            if outlook_office_url:
                links.append(
                    f'<a class="btn secondary" href="{outlook_office_url}" target="_blank" rel="noopener">Outlook 365</a>'
                )
            calendar_block = f"""
                    <p><strong>Calendar</strong></p>
                    <div style="display:flex;flex-wrap:wrap;gap:10px;">{"".join(links)}</div>
            """
        attach_note = (
            "<p style=\"font-size:12px;color:#777;\">Attached: <code>appointment.ics</code></p>"
            if ics_base64
            else ""
        )
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #3d5a4a; color: white; padding: 24px; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 24px; border-radius: 0 0 10px 10px; }}
                .btn {{ display: inline-block; background: #4a7c59; color: white !important; padding: 10px 16px; text-decoration: none; border-radius: 5px; font-size: 14px; }}
                .btn.secondary {{ background: #5a6b8c; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin:0;">Hi {practitioner_first_name},</h2>
                    <p style="margin:8px 0 0 0;">A new appointment was booked for you.</p>
                </div>
                <div class="content">
                    <p><strong>Client:</strong> {customer_name}</p>
                    <p><strong>Service:</strong> {service_name}</p>
                    <p><strong>When:</strong> {date} at {time}</p>
                    <p><strong>Booking ID:</strong> {booking_id[:8].upper()}</p>
                    <p>Payment is expected at the front desk unless otherwise arranged.</p>
                    {calendar_block}
                    {attach_note}
                </div>
            </div>
        </body>
        </html>
        """
        attachments = None
        if ics_base64:
            attachments = [{"filename": "appointment.ics", "content_base64": ics_base64}]
        return await self.send_email(to_email, subject, html_content, attachments=attachments)
    
    async def send_booking_reminder(
        self,
        to_email: str,
        customer_name: str,
        service_name: str,
        date: str,
        time: str
    ) -> Dict[str, Any]:
        """Send booking reminder email"""
        subject = f"Reminder: Your Appointment Tomorrow - The Natural Path Spa"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #4a7c59 0%, #6b8f71 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .highlight {{ background: #fff3cd; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>The Natural Path</h1>
                    <p>Appointment Reminder</p>
                </div>
                <div class="content">
                    <h2>Hello {customer_name},</h2>
                    <p>This is a friendly reminder about your upcoming appointment.</p>
                    
                    <div class="highlight">
                        <strong>{service_name}</strong><br>
                        Date: {date}<br>
                        Time: {time}
                    </div>
                    
                    <p>We look forward to seeing you!</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return await self.send_email(to_email, subject, html_content)
    
    async def send_cancellation_notice(
        self,
        to_email: str,
        customer_name: str,
        service_name: str,
        date: str,
        time: str
    ) -> Dict[str, Any]:
        """Send booking cancellation email"""
        subject = f"Booking Cancelled - The Natural Path Spa"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #dc3545; color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Booking Cancelled</h1>
                </div>
                <div class="content">
                    <h2>Hello {customer_name},</h2>
                    <p>Your booking has been cancelled as requested.</p>
                    <p><strong>Service:</strong> {service_name}</p>
                    <p><strong>Original Date:</strong> {date} at {time}</p>
                    <p>We hope to see you again soon!</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return await self.send_email(to_email, subject, html_content)
    
    async def send_welcome_email(
        self,
        to_email: str,
        customer_name: str
    ) -> Dict[str, Any]:
        """Send welcome email to new customers"""
        subject = f"Welcome to The Natural Path Spa!"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #4a7c59 0%, #6b8f71 100%); color: white; padding: 40px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .btn {{ display: inline-block; background: #4a7c59; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Welcome to The Natural Path</h1>
                    <p>Your Journey to Wellness Begins</p>
                </div>
                <div class="content">
                    <h2>Hello {customer_name},</h2>
                    <p>Welcome to The Natural Path Spa! We're thrilled to have you join our wellness community.</p>
                    <p>At The Natural Path, we believe in holistic healing and personalized care. Our expert practitioners are dedicated to helping you achieve balance and well-being.</p>
                    <p>Ready to book your first appointment?</p>
                    <a href="#" class="btn">Explore Our Services</a>
                </div>
            </div>
        </body>
        </html>
        """
        
        return await self.send_email(to_email, subject, html_content)

    async def send_verification_otp(
        self,
        to_email: str,
        otp_code: str,
        expires_minutes: int = 10
    ) -> Dict[str, Any]:
        """Send account verification OTP email."""
        subject = "Your The Natural Path verification code"
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; color: #1f2937;">
            <h2 style="margin-bottom: 8px;">Verify your email</h2>
            <p>Use the code below to verify your account:</p>
            <div style="font-size: 28px; letter-spacing: 6px; font-weight: 700; margin: 16px 0;">
                {otp_code}
            </div>
            <p>This code expires in {expires_minutes} minutes.</p>
            <p>If you did not request this code, you can ignore this email.</p>
        </body>
        </html>
        """
        text_content = f"Your The Natural Path verification code is {otp_code}. It expires in {expires_minutes} minutes."
        return await self.send_email(to_email, subject, html_content, text_content)

    async def send_booking_invoice(
        self,
        to_email: str,
        customer_name: str,
        service_name: str,
        date: str,
        time: str,
        booking_id: str,
        amount: float,
        pay_link_url: str,
        expires_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Invoice with hosted pay link for a confirmed booking (card_online path)."""
        parsed = urlparse(pay_link_url or "")
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("pay_link_url must be https://")
        e = lambda v: html.escape(str(v or ""), quote=True)  # noqa: E731
        safe_url = e(pay_link_url)
        subject = f"Invoice for your appointment on {e(date)}"
        expires_line = (
            f"<p style='font-size:12px;color:#6b7280;'>Link expires {e(expires_at)}.</p>"
            if expires_at
            else ""
        )
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; color: #1f2937;">
            <h2>Hello {e(customer_name)},</h2>
            <p>Your booking is confirmed. You can pay online now or at the counter when you arrive.</p>
            <div style="border:1px solid #e5e7eb; border-radius:8px; padding:12px; max-width:420px;">
                <p><strong>Service:</strong> {e(service_name)}</p>
                <p><strong>When:</strong> {e(date)} at {e(time)}</p>
                <p><strong>Booking:</strong> {e(booking_id[:8].upper())}</p>
                <p><strong>Amount:</strong> ${amount:.2f}</p>
            </div>
            <p style="margin-top:16px;">
                <a href="{safe_url}" style="display:inline-block; background:#4a7c59; color:#fff; padding:12px 18px; text-decoration:none; border-radius:6px;">
                    Pay securely now
                </a>
            </p>
            <p style="font-size:13px;color:#4a5568;">Prefer to pay at the front desk? That's still OK — just bring your booking id.</p>
            {expires_line}
        </body>
        </html>
        """
        return await self.send_email(to_email, subject, html_content)

    async def send_booking_receipt(
        self,
        to_email: str,
        customer_name: str,
        service_name: str,
        date: str,
        time: str,
        booking_id: str,
        amount: float,
        receipt_id: Optional[str] = None,
        payment_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Branded receipt email for a booking payment (either card_online or walk_in)."""
        e = lambda v: html.escape(str(v or ""), quote=True)  # noqa: E731
        subject = f"Payment receipt for your appointment on {e(date)}"
        mode_line = ""
        if payment_mode == "card_online":
            mode_line = "<p>Paid online — thank you!</p>"
        elif payment_mode == "walk_in":
            mode_line = "<p>Payment received at the front desk — thank you!</p>"
        receipt_line = (
            f"<p><strong>Receipt ID:</strong> {e(receipt_id)}</p>"
            if receipt_id
            else ""
        )
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; color: #1f2937;">
            <h2>Hello {e(customer_name)},</h2>
            {mode_line}
            <div style="border:1px solid #e5e7eb; border-radius:8px; padding:12px; max-width:420px;">
                <p><strong>Service:</strong> {e(service_name)}</p>
                <p><strong>When:</strong> {e(date)} at {e(time)}</p>
                <p><strong>Booking:</strong> {e(booking_id[:8].upper())}</p>
                <p><strong>Amount:</strong> ${amount:.2f}</p>
                {receipt_line}
            </div>
            <p style="margin-top:14px; font-size: 13px; color:#6b7280;">
                If you need a refund, it will settle back to the original payment method within
                3 business days.
            </p>
        </body>
        </html>
        """
        return await self.send_email(to_email, subject, html_content)

    async def send_store_payment_link(
        self,
        to_email: str,
        order_id: str,
        pay_link_url: str,
        expires_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Hardened email with an HTTPS-only hosted pay link for a store order."""
        parsed = urlparse(pay_link_url or "")
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("pay_link_url must be https://")
        e = lambda v: html.escape(str(v or ""), quote=True)  # noqa: E731
        safe_url = e(pay_link_url)
        short_id = e((order_id or "")[-8:].upper())
        expires_line = (
            f"<p style='font-size:12px;color:#6b7280;'>Link expires {e(expires_at)}.</p>"
            if expires_at
            else ""
        )
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; color: #1f2937;">
            <h2>Complete your payment</h2>
            <p>Your order <strong>{short_id}</strong> is ready for payment.</p>
            <p style="margin-top:16px;">
                <a href="{safe_url}" style="display:inline-block; background:#4a7c59; color:#fff; padding:12px 18px; text-decoration:none; border-radius:6px;">
                    Pay securely now
                </a>
            </p>
            {expires_line}
        </body>
        </html>
        """
        return await self.send_email(
            to_email,
            subject="Complete your Natural Path order payment",
            html_content=html_content,
        )

    async def send_store_receipt(
        self,
        to_email: str,
        order_id: str,
        total: float,
        tax: float,
        subtotal: float,
        transaction_id: str | None = None,
    ) -> Dict[str, Any]:
        """Send a branded store receipt after payment capture."""
        e = lambda v: html.escape(str(v or ""), quote=True)  # noqa: E731
        subject = f"Payment receipt for order {e(order_id[-8:].upper())}"
        tx_line = (
            f"<p><strong>Transaction ID:</strong> {e(transaction_id)}</p>"
            if transaction_id
            else ""
        )
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; color: #1f2937;">
            <h2>Thanks for your purchase</h2>
            <p>Your payment was captured successfully.</p>
            <div style="border:1px solid #e5e7eb; border-radius:8px; padding:12px; max-width:420px;">
                <p><strong>Order:</strong> {e(order_id)}</p>
                <p><strong>Subtotal:</strong> ${subtotal:.2f}</p>
                <p><strong>Tax:</strong> ${tax:.2f}</p>
                <p><strong>Total:</strong> ${total:.2f}</p>
                {tx_line}
            </div>
            <p style="margin-top:14px; font-size: 13px; color:#6b7280;">
                Refunds typically settle back to your payment method in 3 business days.
            </p>
        </body>
        </html>
        """
        return await self.send_email(to_email, subject, html_content)


# Singleton instance
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Get email service singleton"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
