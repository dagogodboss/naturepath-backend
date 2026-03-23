#!/usr/bin/env python3
"""
The Natural Path Spa Management System - Backend API Tests
Comprehensive testing of all API endpoints with authentication flows
"""
import requests
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

class NaturalPathSpaAPITester:
    def __init__(self, base_url="http://localhost:8001"):
        self.base_url = base_url
        self.admin_token = None
        self.practitioner_token = None
        self.customer_token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        
        # Test data storage
        self.test_data = {
            "services": [],
            "practitioners": [],
            "bookings": [],
            "customer_id": None,
            "practitioner_id": None
        }

    def log_test(self, name: str, success: bool, details: str = ""):
        """Log test result"""
        self.tests_run += 1
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {name}")
        if details:
            print(f"    {details}")
        if success:
            self.tests_passed += 1
        else:
            self.failed_tests.append(f"{name}: {details}")

    def make_request(self, method: str, endpoint: str, data: Dict = None, 
                    token: str = None, expected_status: int = 200) -> tuple[bool, Dict]:
        """Make HTTP request with error handling"""
        url = f"{self.base_url}/api/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        if token:
            headers['Authorization'] = f'Bearer {token}'

        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=10)
            elif method == 'PATCH':
                response = requests.patch(url, json=data, headers=headers, timeout=10)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=10)
            else:
                return False, {"error": f"Unsupported method: {method}"}

            success = response.status_code == expected_status
            
            try:
                response_data = response.json()
            except:
                response_data = {"raw_response": response.text}
            
            if not success:
                response_data["status_code"] = response.status_code
                response_data["expected_status"] = expected_status
            
            return success, response_data

        except requests.exceptions.RequestException as e:
            return False, {"error": str(e)}

    def test_health_check(self):
        """Test health check endpoint"""
        success, response = self.make_request('GET', 'health')
        
        if success and response.get('status') == 'healthy':
            self.log_test("Health Check", True, "API is healthy")
        else:
            self.log_test("Health Check", False, f"Response: {response}")

    def test_user_registration(self):
        """Test user registration for different roles"""
        # Test customer registration
        customer_data = {
            "email": "customer@test.com",
            "password": "customer123",
            "first_name": "Test",
            "last_name": "Customer",
            "phone": "+1234567890"
        }
        
        success, response = self.make_request('POST', 'auth/register', customer_data, expected_status=201)
        
        if success:
            self.test_data["customer_id"] = response.get("user_id")
            self.log_test("Customer Registration", True, f"Customer ID: {self.test_data['customer_id']}")
        else:
            self.log_test("Customer Registration", False, f"Response: {response}")

    def test_user_login(self):
        """Test login for all user types"""
        # Test admin login
        admin_login = {
            "email": "admin@thenaturalpath.com",
            "password": "admin123"
        }
        
        success, response = self.make_request('POST', 'auth/login', admin_login)
        
        if success and 'access_token' in response:
            self.admin_token = response['access_token']
            self.log_test("Admin Login", True, "Admin token obtained")
        else:
            self.log_test("Admin Login", False, f"Response: {response}")

        # Test practitioner login
        practitioner_login = {
            "email": "sarah@thenaturalpath.com",
            "password": "practitioner123"
        }
        
        success, response = self.make_request('POST', 'auth/login', practitioner_login)
        
        if success and 'access_token' in response:
            self.practitioner_token = response['access_token']
            self.log_test("Practitioner Login", True, "Practitioner token obtained")
        else:
            self.log_test("Practitioner Login", False, f"Response: {response}")

        # Test customer login
        customer_login = {
            "email": "customer@test.com",
            "password": "customer123"
        }
        
        success, response = self.make_request('POST', 'auth/login', customer_login)
        
        if success and 'access_token' in response:
            self.customer_token = response['access_token']
            self.log_test("Customer Login", True, "Customer token obtained")
        else:
            self.log_test("Customer Login", False, f"Response: {response}")

    def test_token_refresh(self):
        """Test token refresh functionality"""
        if not self.customer_token:
            self.log_test("Token Refresh", False, "No customer token available")
            return

        # First login to get refresh token
        customer_login = {
            "email": "customer@test.com",
            "password": "customer123"
        }
        
        success, response = self.make_request('POST', 'auth/login', customer_login)
        
        if success and 'refresh_token' in response:
            refresh_data = {"refresh_token": response['refresh_token']}
            success, refresh_response = self.make_request('POST', 'auth/refresh', refresh_data)
            
            if success and 'access_token' in refresh_response:
                self.log_test("Token Refresh", True, "New access token obtained")
            else:
                self.log_test("Token Refresh", False, f"Response: {refresh_response}")
        else:
            self.log_test("Token Refresh", False, "No refresh token in login response")

    def test_services_endpoints(self):
        """Test all services endpoints"""
        # Test get all services
        success, response = self.make_request('GET', 'services')
        
        if success and isinstance(response, list):
            self.test_data["services"] = response
            self.log_test("Get All Services", True, f"Found {len(response)} services")
        else:
            self.log_test("Get All Services", False, f"Response: {response}")

        # Test get featured services
        success, response = self.make_request('GET', 'services/featured')
        
        if success and isinstance(response, list):
            featured_count = len(response)
            self.log_test("Get Featured Services", True, f"Found {featured_count} featured services")
        else:
            self.log_test("Get Featured Services", False, f"Response: {response}")

        # Test get service by ID
        if self.test_data["services"]:
            service_id = self.test_data["services"][0]["service_id"]
            success, response = self.make_request('GET', f'services/{service_id}')
            
            if success and response.get("service_id") == service_id:
                self.log_test("Get Service by ID", True, f"Service: {response.get('name')}")
            else:
                self.log_test("Get Service by ID", False, f"Response: {response}")

    def test_practitioners_endpoints(self):
        """Test all practitioners endpoints"""
        # Test get all practitioners
        success, response = self.make_request('GET', 'practitioners')
        
        if success and isinstance(response, list):
            self.test_data["practitioners"] = response
            self.log_test("Get All Practitioners", True, f"Found {len(response)} practitioners")
        else:
            self.log_test("Get All Practitioners", False, f"Response: {response}")

        # Test get featured practitioners
        success, response = self.make_request('GET', 'practitioners/featured')
        
        if success and isinstance(response, list):
            featured_count = len(response)
            self.log_test("Get Featured Practitioners", True, f"Found {featured_count} featured practitioners")
        else:
            self.log_test("Get Featured Practitioners", False, f"Response: {response}")

        # Test get practitioner by ID
        if self.test_data["practitioners"]:
            practitioner_id = self.test_data["practitioners"][0]["practitioner_id"]
            self.test_data["practitioner_id"] = practitioner_id
            success, response = self.make_request('GET', f'practitioners/{practitioner_id}')
            
            if success and response.get("practitioner_id") == practitioner_id:
                self.log_test("Get Practitioner by ID", True, f"Practitioner: {response.get('bio', '')[:50]}...")
            else:
                self.log_test("Get Practitioner by ID", False, f"Response: {response}")

        # Test get practitioner availability
        if self.test_data["practitioner_id"]:
            tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            success, response = self.make_request('GET', f'practitioners/{self.test_data["practitioner_id"]}/availability?date={tomorrow}')
            
            if success and isinstance(response, list):
                self.log_test("Get Practitioner Availability", True, f"Found {len(response)} available slots")
            else:
                self.log_test("Get Practitioner Availability", False, f"Response: {response}")

    def test_booking_flow(self):
        """Test complete booking flow: initiate -> lock-slot -> confirm"""
        if not self.customer_token or not self.test_data["services"] or not self.test_data["practitioners"]:
            self.log_test("Booking Flow", False, "Missing required data (customer token, services, or practitioners)")
            return

        service_id = self.test_data["services"][0]["service_id"]
        practitioner_id = self.test_data["practitioners"][0]["practitioner_id"]
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        # Step 1: Initiate booking
        booking_data = {
            "service_id": service_id,
            "practitioner_id": practitioner_id,
            "slot": {
                "date": tomorrow,
                "start_time": "10:00",
                "end_time": "11:00"
            },
            "notes": "Test booking"
        }

        success, response = self.make_request('POST', 'booking/initiate', booking_data, 
                                            token=self.customer_token, expected_status=201)
        
        if success and 'booking_id' in response:
            booking_id = response['booking_id']
            self.test_data["bookings"].append(booking_id)
            self.log_test("Booking Initiate", True, f"Booking ID: {booking_id}")

            # Step 2: Lock slot
            success, lock_response = self.make_request('POST', f'booking/lock-slot?booking_id={booking_id}', 
                                                     token=self.customer_token)
            
            if success and lock_response.get('status') == 'pending':
                self.log_test("Booking Lock Slot", True, f"Slot locked until: {lock_response.get('locked_until')}")

                # Step 3: Confirm booking
                confirm_data = {
                    "booking_id": booking_id,
                    "payment_method": "card"
                }

                success, confirm_response = self.make_request('POST', 'booking/confirm', confirm_data, 
                                                            token=self.customer_token)
                
                if success and confirm_response.get('status') == 'confirmed':
                    self.log_test("Booking Confirm", True, f"Booking confirmed with REVEL order: {confirm_response.get('revel_order_id')}")
                else:
                    self.log_test("Booking Confirm", False, f"Response: {confirm_response}")
            else:
                self.log_test("Booking Lock Slot", False, f"Response: {lock_response}")
        else:
            self.log_test("Booking Initiate", False, f"Response: {response}")

    def test_booking_retrieval(self):
        """Test booking retrieval endpoints"""
        if not self.test_data["bookings"] or not self.customer_token:
            self.log_test("Booking Retrieval", False, "No bookings or customer token available")
            return

        booking_id = self.test_data["bookings"][0]

        # Test get booking by ID
        success, response = self.make_request('GET', f'booking/{booking_id}', token=self.customer_token)
        
        if success and response.get('booking_id') == booking_id:
            self.log_test("Get Booking by ID", True, f"Status: {response.get('status')}")
        else:
            self.log_test("Get Booking by ID", False, f"Response: {response}")

    def test_user_profile_endpoints(self):
        """Test user profile endpoints"""
        if not self.customer_token:
            self.log_test("User Profile", False, "No customer token available")
            return

        # Test get current user profile
        success, response = self.make_request('GET', 'me', token=self.customer_token)
        
        if success and 'user_id' in response:
            self.log_test("Get User Profile", True, f"User: {response.get('first_name')} {response.get('last_name')}")
        else:
            self.log_test("Get User Profile", False, f"Response: {response}")

        # Test get user's bookings
        success, response = self.make_request('GET', 'me/bookings', token=self.customer_token)
        
        if success and isinstance(response, list):
            self.log_test("Get User Bookings", True, f"Found {len(response)} bookings")
        else:
            self.log_test("Get User Bookings", False, f"Response: {response}")

    def test_admin_endpoints(self):
        """Test admin-only endpoints"""
        if not self.admin_token:
            self.log_test("Admin Endpoints", False, "No admin token available")
            return

        # Test admin stats
        success, response = self.make_request('GET', 'admin/stats', token=self.admin_token)
        
        if success and 'total_bookings' in response:
            self.log_test("Admin Stats", True, f"Total bookings: {response.get('total_bookings')}")
        else:
            self.log_test("Admin Stats", False, f"Response: {response}")

        # Test booking analytics
        success, response = self.make_request('GET', 'admin/analytics/bookings', token=self.admin_token)
        
        if success:
            self.log_test("Admin Booking Analytics", True, "Analytics data retrieved")
        else:
            self.log_test("Admin Booking Analytics", False, f"Response: {response}")

    def test_booking_cancellation(self):
        """Test booking cancellation"""
        if not self.test_data["bookings"] or not self.customer_token:
            self.log_test("Booking Cancellation", False, "No bookings or customer token available")
            return

        # Create a new booking to cancel
        if not self.test_data["services"] or not self.test_data["practitioners"]:
            self.log_test("Booking Cancellation", False, "Missing services or practitioners data")
            return

        service_id = self.test_data["services"][0]["service_id"]
        practitioner_id = self.test_data["practitioners"][0]["practitioner_id"]
        tomorrow = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')

        # Create booking to cancel
        booking_data = {
            "service_id": service_id,
            "practitioner_id": practitioner_id,
            "slot": {
                "date": tomorrow,
                "start_time": "14:00",
                "end_time": "15:00"
            },
            "notes": "Test booking for cancellation"
        }

        success, response = self.make_request('POST', 'booking/initiate', booking_data, 
                                            token=self.customer_token, expected_status=201)
        
        if success and 'booking_id' in response:
            booking_id = response['booking_id']
            
            # Cancel the booking
            cancel_data = {
                "booking_id": booking_id,
                "reason": "Test cancellation"
            }

            success, cancel_response = self.make_request('POST', 'booking/cancel', cancel_data, 
                                                       token=self.customer_token)
            
            if success and cancel_response.get('status') == 'cancelled':
                self.log_test("Booking Cancellation", True, f"Booking {booking_id} cancelled")
            else:
                self.log_test("Booking Cancellation", False, f"Response: {cancel_response}")
        else:
            self.log_test("Booking Cancellation", False, f"Failed to create booking: {response}")

    def test_unauthorized_access(self):
        """Test unauthorized access scenarios"""
        # Test accessing protected endpoint without token
        success, response = self.make_request('GET', 'me', expected_status=401)
        
        if not success and response.get('status_code') == 401:
            self.log_test("Unauthorized Access (No Token)", True, "Correctly rejected")
        else:
            self.log_test("Unauthorized Access (No Token)", False, f"Response: {response}")

        # Test accessing admin endpoint with customer token
        if self.customer_token:
            success, response = self.make_request('GET', 'admin/stats', token=self.customer_token, expected_status=403)
            
            if not success and response.get('status_code') == 403:
                self.log_test("Unauthorized Access (Customer to Admin)", True, "Correctly rejected")
            else:
                self.log_test("Unauthorized Access (Customer to Admin)", False, f"Response: {response}")

    def run_all_tests(self):
        """Run all tests in sequence"""
        print("🚀 Starting The Natural Path Spa API Tests")
        print("=" * 60)

        # Basic tests
        self.test_health_check()
        
        # Authentication tests
        self.test_user_registration()
        self.test_user_login()
        self.test_token_refresh()
        
        # Service tests
        self.test_services_endpoints()
        
        # Practitioner tests
        self.test_practitioners_endpoints()
        
        # Booking flow tests
        self.test_booking_flow()
        self.test_booking_retrieval()
        self.test_booking_cancellation()
        
        # User profile tests
        self.test_user_profile_endpoints()
        
        # Admin tests
        self.test_admin_endpoints()
        
        # Security tests
        self.test_unauthorized_access()

        # Print results
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        
        if self.failed_tests:
            print("\n❌ Failed Tests:")
            for failure in self.failed_tests:
                print(f"  - {failure}")
        
        success_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0
        print(f"\n✨ Success Rate: {success_rate:.1f}%")
        
        return self.tests_passed == self.tests_run

def main():
    """Main test execution"""
    tester = NaturalPathSpaAPITester()
    
    try:
        success = tester.run_all_tests()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\n💥 Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())