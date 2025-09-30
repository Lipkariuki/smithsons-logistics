# utils/sms.py
from services.africastalking_client import sms

SENDER_ID = "Smithsons"


def send_sms(recipients: list[str], message: str):
    try:
        response = sms.send(message, recipients, senderId=SENDER_ID)
        print("SMS sent:", response)
        return response
    except Exception as e:
        print("SMS Error:", e)
        return {"error": str(e)}
