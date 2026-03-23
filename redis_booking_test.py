#!/usr/bin/env python3
"""
Focused test for booking confirmation and cancellation after Redis fix
"""
import requests
import sys
import json
from datetime import datetime, timedelta

def test_booking_flow_with_redis():
    """Test booking flow with Redis working"""
    base_url = "http://localhost:8001"
    
    # Login as customer
    login_data = {
        "email": "customer@test.com",
        "password": "customer123"
    }
    
    response = requests.post(f"{base_url}/api/auth/login", json=login_data, timeout=30)
    if response.status_code != 200:
        print(f"❌ Login failed: {response.text}")
        return False
    
    token = response.json()['access_token']
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    # Get services and practitioners
    services = requests.get(f"{base_url}/api/services", timeout=30).json()
    practitioners = requests.get(f"{base_url}/api/practitioners", timeout=30).json()
    
    if not services or not practitioners:
        print("❌ No services or practitioners found")
        return False
    
    service_id = services[0]["service_id"]
    practitioner_id = practitioners[0]["practitioner_id"]
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    print(f"🧪 Testing booking flow with service: {services[0]['name']}")
    
    # Step 1: Initiate booking
    booking_data = {
        "service_id": service_id,
        "practitioner_id": practitioner_id,
        "slot": {
            "date": tomorrow,
            "start_time": "11:00",
            "end_time": "12:00"
        },
        "notes": "Redis test booking"
    }
    
    response = requests.post(f"{base_url}/api/booking/initiate", json=booking_data, 
                           headers=headers, timeout=30)
    
    if response.status_code != 201:
        print(f"❌ Booking initiate failed: {response.text}")
        return False
    
    booking_id = response.json()['booking_id']
    print(f"✅ Booking initiated: {booking_id}")
    
    # Step 2: Lock slot
    response = requests.post(f"{base_url}/api/booking/lock-slot?booking_id={booking_id}", 
                           headers=headers, timeout=30)
    
    if response.status_code != 200:
        print(f"❌ Slot lock failed: {response.text}")
        return False
    
    print(f"✅ Slot locked: {response.json().get('locked_until')}")
    
    # Step 3: Confirm booking (with longer timeout for REVEL processing)
    confirm_data = {
        "booking_id": booking_id,
        "payment_method": "card"
    }
    
    print("🔄 Confirming booking (this may take a moment for REVEL processing)...")
    response = requests.post(f"{base_url}/api/booking/confirm", json=confirm_data, 
                           headers=headers, timeout=60)  # Longer timeout
    
    if response.status_code != 200:
        print(f"❌ Booking confirm failed: {response.text}")
        return False
    
    result = response.json()
    print(f"✅ Booking confirmed: {result.get('status')}")
    print(f"   REVEL Order ID: {result.get('revel_order_id')}")
    print(f"   Payment ID: {result.get('payment', {}).get('payment_id')}")
    
    # Test cancellation
    print("\n🧪 Testing booking cancellation...")
    
    # Create another booking to cancel
    booking_data["slot"]["start_time"] = "13:00"
    booking_data["slot"]["end_time"] = "14:00"
    booking_data["notes"] = "Booking for cancellation test"
    
    response = requests.post(f"{base_url}/api/booking/initiate", json=booking_data, 
                           headers=headers, timeout=30)
    
    if response.status_code == 201:
        cancel_booking_id = response.json()['booking_id']
        
        cancel_data = {
            "booking_id": cancel_booking_id,
            "reason": "Test cancellation with Redis"
        }
        
        print("🔄 Cancelling booking...")
        response = requests.post(f"{base_url}/api/booking/cancel", json=cancel_data, 
                               headers=headers, timeout=60)  # Longer timeout
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Booking cancelled: {result.get('status')}")
            return True
        else:
            print(f"❌ Booking cancel failed: {response.text}")
            return False
    else:
        print(f"❌ Failed to create booking for cancellation: {response.text}")
        return False

if __name__ == "__main__":
    print("🚀 Testing booking flow with Redis enabled")
    print("=" * 50)
    
    success = test_booking_flow_with_redis()
    
    if success:
        print("\n✅ All booking flow tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed")
        sys.exit(1)