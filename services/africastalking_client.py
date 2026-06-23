# services/africastalking_client.py
import os

import africastalking

# Allow overriding credentials via environment variables; do not hard-code secrets.
USERNAME = os.getenv("AFRICASTALKING_USERNAME", "smithsons")
API_KEY = os.getenv("AFRICASTALKING_API_KEY")

if not API_KEY:
    raise RuntimeError("AFRICASTALKING_API_KEY must be set in environment variables")

africastalking.initialize(USERNAME, API_KEY)
sms = africastalking.SMS
