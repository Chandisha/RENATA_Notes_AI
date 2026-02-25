import meeting_database as db
import time
import random

class PaymentService:
    def __init__(self):
        self.pricing = {
            "single_meeting": 99,  # INR
            "pro_monthly": 499,
            "enterprise": 2499
        }

    def generate_payment_link(self, email, item_type, meeting_id=None):
        """Simulate creating a Stripe/Razorpay checkout session"""
        amount = self.pricing.get(item_type, 0)
        payment_id = f"PAY_{int(time.time())}_{random.randint(1000, 9999)}"
        
        # In a real app, this would return a URL to the gateway
        return {
            "status": "success",
            "payment_id": payment_id,
            "amount": amount,
            "email": email,
            "item": item_type,
            "meeting_id": meeting_id,
            "checkout_url": f"https://rena.ai/checkout/{payment_id}"
        }

    def process_simulated_payment(self, email, item_type, meeting_id=None):
        """
        Simulate a successful payment webhook/callback.
        In production, this would be triggered by a gateway notification.
        """
        # Simulate network delay
        time.sleep(1)
        
        if item_type == "single_meeting" and meeting_id:
            db.add_credits(email, 1)
            success, msg = db.unlock_meeting_summary(email, meeting_id)
            return success, msg
        
        elif item_type == "pro_monthly":
            success = db.update_user_plan(email, "Pro")
            return success, "Upgraded to Pro successfully"
            
        elif item_type == "enterprise":
            success = db.update_user_plan(email, "Enterprise")
            return success, "Upgraded to Enterprise successfully"
            
        return False, "Unknown item type"

payments = PaymentService()
