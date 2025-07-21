# utils/sms.py
from services.africastalking_client import sms

def send_sms(recipients: list[str], message: str):
    try:
        response = sms.send(message, recipients)
        print("SMS sent:", response)
        return response
    except Exception as e:
        print("SMS Error:", e)
        return {"error": str(e)}
