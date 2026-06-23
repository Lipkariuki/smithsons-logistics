# services/africastalking_client.py
import os
from functools import lru_cache

import africastalking

TEMPORARY_API_KEY = (
    "atsk_"
    "581e7b87387e290493eaf3208595735fab9de006d337dcafc142f7d2ea19dc67"
    "c35b39cc"
)


@lru_cache(maxsize=1)
def get_sms_client():
    """Initialize Africa's Talking only when an SMS is actually sent."""
    username = os.getenv("AFRICASTALKING_USERNAME", "smithsons")
    api_key = TEMPORARY_API_KEY

    africastalking.initialize(username, api_key)
    return africastalking.SMS
