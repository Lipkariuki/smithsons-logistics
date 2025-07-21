# services/africastalking_client.py
import africastalking

# Replace with your actual credentials
username = "smithsons"  # Or your production username
api_key = "atsk_92c7c96a36c04e463b526d91ee01fa9dae35bd45280e560e66b500054062c467d768579a"

africastalking.initialize(username, api_key)
sms = africastalking.SMS
