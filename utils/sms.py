import os

from services.africastalking_client import get_sms_client

SENDER_ID = os.getenv("AFRICASTALKING_SENDER_ID", "Smithsons")


def _normalize_phone(phone: str) -> str:
    value = phone.strip().replace(" ", "").replace("-", "")
    if value.startswith("+"):
        return value
    if value.startswith("254"):
        return f"+{value}"
    if value.startswith("0") and len(value) == 10:
        return f"+254{value[1:]}"
    return value


def send_sms(recipients: list[str], message: str):
    try:
        normalized_recipients = list(
            dict.fromkeys(_normalize_phone(phone) for phone in recipients if phone)
        )
        if not normalized_recipients:
            raise ValueError("At least one SMS recipient is required")

        sms = get_sms_client()
        try:
            response = sms.send(
                message,
                normalized_recipients,
                sender_id=SENDER_ID,
            )
        except TypeError as err:
            err_msg = str(err)
            if "sender_id" in err_msg and "unexpected" in err_msg:
                try:
                    response = sms.send(
                        message,
                        normalized_recipients,
                        senderId=SENDER_ID,
                    )  # type: ignore[arg-type]
                except TypeError as err2:
                    if "senderId" in str(err2) and "unexpected" in str(err2):
                        response = sms.send(message, normalized_recipients)
                    else:
                        raise
            elif "senderId" in err_msg and "unexpected" in err_msg:
                response = sms.send(
                    message,
                    normalized_recipients,
                    sender_id=SENDER_ID,
                )
            else:
                raise
        print("SMS sent:", response)
        return response
    except Exception as e:
        print("SMS Error:", e)
        return {"error": str(e)}
