"""
REVEL POS Integration Service - MOCK Implementation
All bookings and payments flow through this abstraction layer
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
import asyncio

logger = logging.getLogger(__name__)


class RevelOrder(BaseModel):
    """REVEL Order representation"""
    order_id: str
    establishment_id: int
    customer_id: Optional[str] = None
    items: List[Dict[str, Any]] = []
    subtotal: float
    tax: float
    total: float
    status: str = "open"
    created_at: datetime
    updated_at: datetime
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class RevelPayment(BaseModel):
    """REVEL Payment representation"""
    transaction_id: str
    order_id: str
    amount: float
    payment_method: str
    status: str = "pending"
    created_at: datetime
    
    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class RevelProduct(BaseModel):
    """REVEL Product/Service representation"""
    product_id: str
    name: str
    price: float
    category: str
    is_active: bool = True


class RevelService:
    """
    REVEL POS Integration Service - MOCK
    
    This abstraction layer handles all communication with REVEL POS.
    In production, this would make actual API calls to REVEL.
    """
    
    def __init__(self):
        self._orders: Dict[str, RevelOrder] = {}
        self._payments: Dict[str, RevelPayment] = {}
        self._products: Dict[str, RevelProduct] = {}
        self._initialize_mock_products()
    
    def _initialize_mock_products(self):
        """Initialize mock products/services in REVEL"""
        mock_products = [
            {"product_id": "revel_svc_001", "name": "Swedish Massage", "price": 120.00, "category": "massage"},
            {"product_id": "revel_svc_002", "name": "Deep Tissue Massage", "price": 150.00, "category": "massage"},
            {"product_id": "revel_svc_003", "name": "Hot Stone Massage", "price": 175.00, "category": "massage"},
            {"product_id": "revel_svc_004", "name": "Aromatherapy Facial", "price": 95.00, "category": "facial"},
            {"product_id": "revel_svc_005", "name": "Anti-Aging Facial", "price": 145.00, "category": "facial"},
            {"product_id": "revel_svc_006", "name": "Body Wrap Treatment", "price": 130.00, "category": "body_treatment"},
            {"product_id": "revel_svc_007", "name": "Wellness Consultation", "price": 75.00, "category": "wellness"},
            {"product_id": "revel_svc_008", "name": "Holistic Healing Session", "price": 200.00, "category": "holistic"},
        ]
        for p in mock_products:
            self._products[p["product_id"]] = RevelProduct(**p)
    
    async def validate_service(self, revel_product_id: str) -> Optional[Dict[str, Any]]:
        """
        Validate that a service exists in REVEL POS
        
        Args:
            revel_product_id: The REVEL product ID
            
        Returns:
            Product details if valid, None otherwise
        """
        await asyncio.sleep(0.1)  # Simulate API latency
        
        product = self._products.get(revel_product_id)
        if product and product.is_active:
            logger.info(f"REVEL: Service validated - {revel_product_id}")
            return product.model_dump()
        
        logger.warning(f"REVEL: Service not found - {revel_product_id}")
        return None
    
    async def get_all_products(self) -> List[Dict[str, Any]]:
        """Get all active products from REVEL"""
        await asyncio.sleep(0.1)
        return [p.model_dump() for p in self._products.values() if p.is_active]
    
    async def create_order(
        self,
        customer_id: str,
        items: List[Dict[str, Any]],
        establishment_id: int = 1
    ) -> Dict[str, Any]:
        """
        Create a new order in REVEL POS
        
        Args:
            customer_id: Customer identifier
            items: List of order items with product_id, quantity, price
            establishment_id: REVEL establishment ID
            
        Returns:
            Created order details
        """
        await asyncio.sleep(0.2)  # Simulate API latency
        
        order_id = f"REVEL_ORD_{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)
        
        subtotal = sum(item.get("price", 0) * item.get("quantity", 1) for item in items)
        tax = round(subtotal * 0.0925, 2)  # 9.25% tax (LA rate)
        total = round(subtotal + tax, 2)
        
        order = RevelOrder(
            order_id=order_id,
            establishment_id=establishment_id,
            customer_id=customer_id,
            items=items,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status="open",
            created_at=now,
            updated_at=now
        )
        
        self._orders[order_id] = order
        logger.info(f"REVEL: Order created - {order_id}, Total: ${total}")
        
        return order.model_dump(mode='json')
    
    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order details from REVEL"""
        await asyncio.sleep(0.1)
        order = self._orders.get(order_id)
        return order.model_dump(mode='json') if order else None
    
    async def update_order_status(self, order_id: str, status: str) -> Optional[Dict[str, Any]]:
        """Update order status in REVEL"""
        await asyncio.sleep(0.1)
        
        if order_id in self._orders:
            self._orders[order_id].status = status
            self._orders[order_id].updated_at = datetime.now(timezone.utc)
            logger.info(f"REVEL: Order status updated - {order_id} -> {status}")
            return self._orders[order_id].model_dump(mode='json')
        
        return None
    
    async def process_payment(
        self,
        order_id: str,
        amount: float,
        payment_method: str = "card"
    ) -> Dict[str, Any]:
        """
        Process payment through REVEL POS
        
        Args:
            order_id: The REVEL order ID
            amount: Payment amount
            payment_method: Payment method (card, cash, etc.)
            
        Returns:
            Payment transaction details
        """
        await asyncio.sleep(0.3)  # Simulate payment processing
        
        transaction_id = f"REVEL_TXN_{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)
        
        # Simulate 95% success rate
        import random
        success = random.random() < 0.95
        
        payment = RevelPayment(
            transaction_id=transaction_id,
            order_id=order_id,
            amount=amount,
            payment_method=payment_method,
            status="completed" if success else "failed",
            created_at=now
        )
        
        self._payments[transaction_id] = payment
        
        if success:
            # Update order status
            await self.update_order_status(order_id, "paid")
            logger.info(f"REVEL: Payment processed - {transaction_id}, Amount: ${amount}")
        else:
            logger.warning(f"REVEL: Payment failed - {transaction_id}")
        
        return {
            "success": success,
            "transaction_id": transaction_id,
            "order_id": order_id,
            "amount": amount,
            "status": payment.status,
            "message": "Payment successful" if success else "Payment declined"
        }
    
    async def confirm_payment(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        """Confirm a payment transaction"""
        await asyncio.sleep(0.1)
        payment = self._payments.get(transaction_id)
        return payment.model_dump(mode='json') if payment else None
    
    async def refund_payment(
        self,
        transaction_id: str,
        amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Process refund through REVEL POS
        
        Args:
            transaction_id: Original transaction ID
            amount: Refund amount (None for full refund)
            
        Returns:
            Refund transaction details
        """
        await asyncio.sleep(0.2)
        
        original_payment = self._payments.get(transaction_id)
        if not original_payment:
            return {"success": False, "message": "Original transaction not found"}
        
        refund_amount = amount if amount else original_payment.amount
        refund_id = f"REVEL_REF_{uuid.uuid4().hex[:12].upper()}"
        
        logger.info(f"REVEL: Refund processed - {refund_id}, Amount: ${refund_amount}")
        
        return {
            "success": True,
            "refund_id": refund_id,
            "original_transaction_id": transaction_id,
            "amount": refund_amount,
            "status": "refunded"
        }
    
    async def sync_customer(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Sync customer data with REVEL POS"""
        await asyncio.sleep(0.1)
        
        revel_customer_id = f"REVEL_CUST_{uuid.uuid4().hex[:8].upper()}"
        logger.info(f"REVEL: Customer synced - {revel_customer_id}")
        
        return {
            "revel_customer_id": revel_customer_id,
            "synced": True,
            "email": customer_data.get("email"),
            "name": customer_data.get("name")
        }


# Singleton instance
_revel_service: Optional[RevelService] = None


def get_revel_service() -> RevelService:
    """Get REVEL service singleton"""
    global _revel_service
    if _revel_service is None:
        _revel_service = RevelService()
    return _revel_service
