# services/africastalking_client.py
import os

import africastalking

# Allow overriding credentials via environment variables, fallback to prod defaults
USERNAME = os.getenv("AFRICASTALKING_USERNAME", "smithsons")
API_KEY = os.getenv(
    "AFRICASTALKING_API_KEY",
    "atsk_e65e0f0b53256f66d10b4d39b0a65ce80b528f3e66d06b3c3bf9e7511ea5d346c0a53872",
)

africastalking.initialize(USERNAME, API_KEY)
sms = africastalking.SMS
