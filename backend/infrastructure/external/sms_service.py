"""
SMS Service - Twilio Integration
"""
import os
import asyncio
import logging
from typing import Optional, Dict, Any
from twilio.rest import Client
from core.config import settings

logger = logging.getLogger(__name__)


class SMSService:
    """SMS service using Twilio"""
    
    def __init__(self):
        self.account_sid = settings.twilio_account_sid
        self.auth_token = settings.twilio_auth_token
        self.phone_number = settings.twilio_phone_number
        self.client: Optional[Client] = None
        
        if self.account_sid and self.auth_token and self.account_sid != "placeholder":
            try:
                self.client = Client(self.account_sid, self.auth_token)
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")
    
    async def send_sms(
        self,
        to_phone: str,
        message: str
    ) -> Dict[str, Any]:
        """
        Send SMS using Twilio
        
        Args:
            to_phone: Recipient phone number (E.164 format)
            message: SMS message content
            
        Returns:
            SMS send result
        """
        if not self.client:
            logger.warning("Twilio not configured - SMS not sent")
            return {"success": False, "message": "SMS service not configured", "mock": True}
        
        try:
            # Ensure phone number is in E.164 format
            if not to_phone.startswith('+'):
                to_phone = f'+1{to_phone}'  # Default to US
            
            sms = await asyncio.to_thread(
                self.client.messages.create,
                body=message,
                from_=self.phone_number,
                to=to_phone
            )
            
            logger.info(f"SMS sent to {to_phone}: {sms.sid}")
            return {
                "success": True,
                "message_sid": sms.sid,
                "to": to_phone,
                "status": sms.status
            }
        except Exception as e:
            logger.error(f"Failed to send SMS: {str(e)}")
            return {"success": False, "message": str(e)}
    
    async def send_booking_confirmation_sms(
        self,
        to_phone: str,
        customer_name: str,
        service_name: str,
        date: str,
        time: str
    ) -> Dict[str, Any]:
        """Send booking confirmation SMS"""
        message = (
            f"Hi {customer_name}! Your booking at The Natural Path Spa is confirmed.\n"
            f"Service: {service_name}\n"
            f"Date: {date} at {time}\n"
            f"Please arrive 10-15 min early."
        )
        return await self.send_sms(to_phone, message)
    
    async def send_booking_reminder_sms(
        self,
        to_phone: str,
        customer_name: str,
        service_name: str,
        time: str
    ) -> Dict[str, Any]:
        """Send booking reminder SMS"""
        message = (
            f"Reminder: Hi {customer_name}, you have an appointment tomorrow at "
            f"The Natural Path Spa.\n"
            f"Service: {service_name} at {time}\n"
            f"We look forward to seeing you!"
        )
        return await self.send_sms(to_phone, message)
    
    async def send_cancellation_sms(
        self,
        to_phone: str,
        customer_name: str,
        service_name: str,
        date: str
    ) -> Dict[str, Any]:
        """Send booking cancellation SMS"""
        message = (
            f"Hi {customer_name}, your {service_name} appointment on {date} "
            f"has been cancelled. Hope to see you again soon! - The Natural Path Spa"
        )
        return await self.send_sms(to_phone, message)


# Singleton instance
_sms_service: Optional[SMSService] = None


def get_sms_service() -> SMSService:
    """Get SMS service singleton"""
    global _sms_service
    if _sms_service is None:
        _sms_service = SMSService()
    return _sms_service
