"""
Email Service - Resend Integration
"""
import os
import asyncio
import logging
import resend
from typing import Optional, Dict, Any, List
from core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Email service using Resend"""
    
    def __init__(self):
        self.api_key = settings.resend_api_key
        self.sender_email = settings.sender_email
        if self.api_key:
            resend.api_key = self.api_key
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send an email using Resend
        
        Args:
            to_email: Recipient email
            subject: Email subject
            html_content: HTML content
            text_content: Plain text content (optional)
            
        Returns:
            Email send result
        """
        if not self.api_key or self.api_key == "re_placeholder":
            logger.warning("Resend API key not configured - email not sent")
            return {"success": False, "message": "Email service not configured", "mock": True}
        
        params = {
            "from": self.sender_email,
            "to": [to_email],
            "subject": subject,
            "html": html_content
        }
        
        if text_content:
            params["text"] = text_content
        
        try:
            email = await asyncio.to_thread(resend.Emails.send, params)
            logger.info(f"Email sent to {to_email}: {subject}")
            return {
                "success": True,
                "email_id": email.get("id"),
                "message": f"Email sent to {to_email}"
            }
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return {"success": False, "message": str(e)}
    
    async def send_booking_confirmation(
        self,
        to_email: str,
        customer_name: str,
        service_name: str,
        practitioner_name: str,
        date: str,
        time: str,
        booking_id: str
    ) -> Dict[str, Any]:
        """Send booking confirmation email"""
        subject = f"Booking Confirmed - The Natural Path Spa"
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
                .btn {{ display: inline-block; background: #4a7c59; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin-top: 20px; }}
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
        
        return await self.send_email(to_email, subject, html_content)
    
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


# Singleton instance
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Get email service singleton"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
