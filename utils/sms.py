import os
import logging

from services.africastalking_client import get_sms_client
from settings import ConfigurationError

logger = logging.getLogger(__name__)

SENDER_ID = os.getenv("AFRICASTALKING_SENDER_ID", "Smithsons")


def _accepted(response, expected):
    """API acceptance is not handset delivery. Never log the raw response."""
    if not isinstance(response, dict):
        return False, []
    data = response.get("SMSMessageData")
    recipients = data.get("Recipients") if isinstance(data, dict) else None
    if not isinstance(recipients, list) or len(recipients) != expected:
        return False, []
    codes = []
    accepted = True
    for recipient in recipients:
        if not isinstance(recipient, dict):
            accepted = False
            continue
        code = recipient.get("statusCode")
        # Whitelist diagnostics: provider fields can contain user data or secrets.
        code = int(code) if isinstance(code, (str, int)) and str(code).isdigit() else None
        codes.append(code if code in {100, 101, 102, 401, 402, 403, 404, 405, 406, 407, 500, 501, 502} else None)
        accepted &= code in {100, 101, 102} if code is not None else recipient.get("status") == "Success"
    return accepted, codes


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
        accepted, codes = _accepted(response, len(normalized_recipients))
        if not accepted:
            logger.warning("SMS provider rejected or did not acknowledge all recipients; status_codes=%s", codes)
            return {"error": "SMS was not accepted for all recipients; check provider status", "code": "provider_rejected", "status_codes": codes}
        logger.info("SMS accepted by provider; recipient_count=%s status_codes=%s; handset delivery not confirmed", len(normalized_recipients), codes)
        return response
    except Exception as exc:
        response = getattr(exc, "response", None)
        http_status = getattr(response, "status_code", None)
        http_status = http_status if isinstance(http_status, int) and 100 <= http_status <= 599 else None
        code = "configuration_missing" if isinstance(exc, ConfigurationError) else "provider_authentication" if http_status in {401, 403} else "provider_request_failed"
        logger.warning("SMS request failed; reason=%s http_status=%s; verify provider configuration", code, http_status)
        return {"error": "SMS delivery failed; verify configuration and provider status", "code": code}
