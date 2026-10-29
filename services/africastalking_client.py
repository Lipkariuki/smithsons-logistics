"""Lazy, environment-only SMS client. Never initialize or send at import time."""
from functools import lru_cache
import africastalking
from settings import required_env, ConfigurationError


@lru_cache(maxsize=1)
def get_sms_client():
    username = required_env('AFRICASTALKING_USERNAME')
    api_key = required_env('AFRICASTALKING_API_KEY')
    try:
        africastalking.initialize(username, api_key)
    except Exception:
        raise ConfigurationError('SMS provider initialization failed; verify environment configuration') from None
    return africastalking.SMS
