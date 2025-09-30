# utils/sms.py
from services.africastalking_client import sms

SENDER_ID = "Smithsons"


def send_sms(recipients: list[str], message: str):
    try:
        try:
            response = sms.send(message, recipients, sender_id=SENDER_ID)
        except TypeError as err:
            err_msg = str(err)
            if "sender_id" in err_msg and "unexpected" in err_msg:
                try:
                    response = sms.send(message, recipients, senderId=SENDER_ID)  # type: ignore[arg-type]
                except TypeError as err2:
                    if "senderId" in str(err2) and "unexpected" in str(err2):
                        response = sms.send(message, recipients)
                    else:
                        raise
            elif "senderId" in err_msg and "unexpected" in err_msg:
                response = sms.send(message, recipients, sender_id=SENDER_ID)
            else:
                raise
        print("SMS sent:", response)
        return response
    except Exception as e:
        print("SMS Error:", e)
        return {"error": str(e)}
