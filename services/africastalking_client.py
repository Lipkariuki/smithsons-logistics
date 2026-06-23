# services/africastalking_client.py
import os
from functools import lru_cache

import africastalking

TEMPORARY_API_KEY = (
    "atsk_"
    "e65e0f0b53256f66d10b4d39b0a65ce80b528f3e66d06b3c3bf9e7511ea5d346"
    "c0a53872"
)


@lru_cache(maxsize=1)
def get_sms_client():
    """Initialize Africa's Talking only when an SMS is actually sent."""
    username = os.getenv("AFRICASTALKING_USERNAME", "smithsons")
    api_key = TEMPORARY_API_KEY

    africastalking.initialize(username, api_key)
    return africastalking.SMS
