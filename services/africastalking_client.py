# services/africastalking_client.py
import os
from functools import lru_cache

import africastalking


@lru_cache(maxsize=1)
def get_sms_client():
    """Initialize Africa's Talking only when an SMS is actually sent."""
    username = os.getenv("AFRICASTALKING_USERNAME", "smithsons")
    api_key = os.getenv("AFRICASTALKING_API_KEY")

    if not api_key:
        raise RuntimeError(
            "AFRICASTALKING_API_KEY must be set in environment variables"
        )

    africastalking.initialize(username, api_key)
    return africastalking.SMS
