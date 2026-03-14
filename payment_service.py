import os
import razorpay
import meeting_database as db
from dotenv import load_dotenv

load_dotenv()

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

class RazorpayService:
    def __init__(self):
        print(f">>> RAZORPAY INIT: KEY_ID={'Present' if RAZORPAY_KEY_ID else 'MISSING'}")
        if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
            try:
                self.client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
            except Exception as e:
                print(f">>> RAZORPAY CLIENT INIT FAILED: {e}")
                self.client = None
        else:
            self.client = None
        self.pricing = {
            "single_meeting": 100,  # 1 INR in Paise = 100
            "pro_monthly": 100,     # TEST PRICE: 1 INR in Paise = 100
            "enterprise": 249900    # 2499 INR = 249900
        }

    def create_order(self, email, item_type, meeting_id=None):
        """Create a real Razorpay Order"""
        amount = self.pricing.get(item_type, 100) # Default to 1 INR if not found
        
        data = {
            "amount": amount,
            "currency": "INR",
            "receipt": f"receipt_{email}_{item_type}",
            "notes": {
                "email": email,
                "item_type": item_type,
                "meeting_id": meeting_id
            }
        }
        
        if not self.client:
            return {"status": "error", "message": "Razorpay client not initialized. Check API keys."}

        try:
            order = self.client.order.create(data=data)
            return {
                "status": "success",
                "order_id": order['id'],
                "amount": amount,
                "key": RAZORPAY_KEY_ID
            }
        except Exception as e:
            print(f">>> RAZORPAY ORDER CREATE FAILED: {e}")
            return {"status": "error", "message": f"Razorpay API error: {str(e)}"}

    def verify_payment(self, razorpay_order_id, razorpay_payment_id, razorpay_signature, email, item_type, meeting_id=None):
        """Verify the signature and update the database"""
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }

        try:
            # This will raise an error if signature is invalid
            self.client.utility.verify_payment_signature(params_dict)
            
            # Signature is valid, update DB
            if item_type == "single_meeting" and meeting_id:
                db.unlock_meeting_summary(email, meeting_id)
                return True, "Meeting unlocked successfully"
            
            elif item_type == "pro_monthly":
                db.update_user_plan(email, "Pro")
                return True, "Upgraded to Pro successfully"
                
            elif item_type == "enterprise":
                db.update_user_plan(email, "Enterprise")
                return True, "Upgraded to Enterprise successfully"
            
            return False, "Unknown item type"
        except Exception as e:
            return False, f"Signature verification failed: {str(e)}"

razorpay_service = RazorpayService()
