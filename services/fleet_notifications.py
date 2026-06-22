import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import SessionLocal
from models import (
    FleetDriverCompliance,
    FleetNotificationHistory,
    FleetVehicleCompliance,
    User,
    Vehicle,
)
from utils.sms import send_sms

logger = logging.getLogger(__name__)

EXPIRY_REMINDER_DAYS = (30, 14, 7, 1)
SERVICE_REMINDER_KM = (1000, 500, 100, 0)


def _normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    value = phone.strip().replace(" ", "").replace("-", "")
    if value.startswith("+"):
        return value
    if value.startswith("254"):
        return f"+{value}"
    if value.startswith("0") and len(value) == 10:
        return f"+254{value[1:]}"
    return value


def _notification_recipients(db: Session) -> list[str]:
    configured = os.getenv("FLEET_NOTIFICATION_RECIPIENTS", "")
    raw_recipients: Iterable[str]
    if configured.strip():
        raw_recipients = configured.split(",")
    else:
        raw_recipients = (
            phone
            for (phone,) in db.query(User.phone)
            .filter(User.role == "admin", User.phone.isnot(None))
            .all()
        )

    recipients = {_normalize_phone(phone) for phone in raw_recipients}
    return sorted(phone for phone in recipients if phone)


def _provider_response_text(response) -> str:
    try:
        return json.dumps(response, default=str)
    except TypeError:
        return str(response)


def _send_once(
    db: Session,
    *,
    deduplication_key: str,
    entity_type: str,
    entity_id: int,
    notification_type: str,
    reminder_threshold: str,
    recipient: str,
    message: str,
    due_date: date | None = None,
    due_mileage: int | None = None,
) -> str:
    existing = (
        db.query(FleetNotificationHistory)
        .filter(FleetNotificationHistory.deduplication_key == deduplication_key)
        .first()
    )
    if existing and existing.status in {"pending", "sent"}:
        return "skipped"

    if existing:
        history = existing
        history.status = "pending"
        history.provider_response = None
    else:
        history = FleetNotificationHistory(
            deduplication_key=deduplication_key,
            entity_type=entity_type,
            entity_id=entity_id,
            notification_type=notification_type,
            reminder_threshold=reminder_threshold,
            recipient=recipient,
            message=message,
            due_date=due_date,
            due_mileage=due_mileage,
            status="pending",
        )
        db.add(history)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "skipped"

    response = send_sms([recipient], message)
    failed = isinstance(response, dict) and bool(response.get("error"))
    history.status = "failed" if failed else "sent"
    history.provider_response = _provider_response_text(response)
    history.sent_at = None if failed else datetime.utcnow()
    db.commit()
    return history.status


def _record_result(result: str, totals: dict[str, int]) -> None:
    if result == "sent":
        totals["sent"] += 1
    elif result == "failed":
        totals["failed"] += 1
    else:
        totals["skipped"] += 1


def run_fleet_notification_checks(
    db: Session,
    *,
    today: date | None = None,
) -> dict[str, int]:
    """Run fleet checks without importing or invoking operational workflows."""

    check_date = today or date.today()
    recipients = _notification_recipients(db)
    totals = {"checked": 0, "sent": 0, "skipped": 0, "failed": 0}

    if not recipients:
        logger.warning("Fleet notification check skipped: no admin SMS recipients configured")
        return totals

    vehicle_rows = (
        db.query(FleetVehicleCompliance, Vehicle)
        .join(Vehicle, Vehicle.id == FleetVehicleCompliance.vehicle_id)
        .all()
    )
    for compliance, vehicle in vehicle_rows:
        expiry_checks = (
            (
                "insurance_expiry",
                compliance.insurance_expiry_date,
                f"Insurance for {vehicle.plate_number}",
            ),
            (
                "inspection_expiry",
                compliance.inspection_expiry_date,
                f"Inspection for {vehicle.plate_number}",
            ),
        )
        for notification_type, due_date, label in expiry_checks:
            if not due_date:
                continue
            totals["checked"] += 1
            days_remaining = (due_date - check_date).days
            if days_remaining not in EXPIRY_REMINDER_DAYS:
                continue
            message = (
                f"Smithsons Fleet reminder: {label} expires in {days_remaining} "
                f"day{'s' if days_remaining != 1 else ''} on {due_date:%d %b %Y}."
            )
            for recipient in recipients:
                key = (
                    f"{notification_type}:vehicle:{vehicle.id}:"
                    f"{due_date.isoformat()}:{days_remaining}:{recipient}"
                )
                result = _send_once(
                    db,
                    deduplication_key=key,
                    entity_type="vehicle",
                    entity_id=vehicle.id,
                    notification_type=notification_type,
                    reminder_threshold=f"{days_remaining}_days",
                    recipient=recipient,
                    message=message,
                    due_date=due_date,
                )
                _record_result(result, totals)

        if (
            compliance.current_mileage is not None
            and compliance.next_service_due_mileage is not None
        ):
            totals["checked"] += 1
            km_remaining = (
                compliance.next_service_due_mileage - compliance.current_mileage
            )
            if km_remaining <= 0:
                threshold = 0
            else:
                eligible = [
                    value for value in SERVICE_REMINDER_KM if value >= km_remaining and value > 0
                ]
                threshold = min(eligible) if eligible else None

            if threshold is not None:
                if threshold == 0:
                    status_text = f"is due now/overdue by {abs(km_remaining):,} km"
                else:
                    status_text = f"is due in {km_remaining:,} km"
                message = (
                    f"Smithsons Fleet reminder: Service for {vehicle.plate_number} "
                    f"{status_text}. Current mileage: {compliance.current_mileage:,} km; "
                    f"due at {compliance.next_service_due_mileage:,} km."
                )
                for recipient in recipients:
                    key = (
                        f"service_due:vehicle:{vehicle.id}:"
                        f"{compliance.next_service_due_mileage}:{threshold}:{recipient}"
                    )
                    result = _send_once(
                        db,
                        deduplication_key=key,
                        entity_type="vehicle",
                        entity_id=vehicle.id,
                        notification_type="service_due",
                        reminder_threshold=f"{threshold}_km",
                        recipient=recipient,
                        message=message,
                        due_mileage=compliance.next_service_due_mileage,
                    )
                    _record_result(result, totals)

    driver_rows = (
        db.query(FleetDriverCompliance, User)
        .join(User, User.id == FleetDriverCompliance.driver_id)
        .filter(User.role == "driver")
        .all()
    )
    for compliance, driver in driver_rows:
        due_date = compliance.driver_license_expiry_date
        if not due_date:
            continue
        totals["checked"] += 1
        days_remaining = (due_date - check_date).days
        if days_remaining not in EXPIRY_REMINDER_DAYS:
            continue
        message = (
            f"Smithsons Fleet reminder: Driver license for {driver.name} expires in "
            f"{days_remaining} day{'s' if days_remaining != 1 else ''} "
            f"on {due_date:%d %b %Y}."
        )
        for recipient in recipients:
            key = (
                f"driver_license_expiry:driver:{driver.id}:"
                f"{due_date.isoformat()}:{days_remaining}:{recipient}"
            )
            result = _send_once(
                db,
                deduplication_key=key,
                entity_type="driver",
                entity_id=driver.id,
                notification_type="driver_license_expiry",
                reminder_threshold=f"{days_remaining}_days",
                recipient=recipient,
                message=message,
                due_date=due_date,
            )
            _record_result(result, totals)

    return totals


async def fleet_notification_scheduler() -> None:
    """Run once daily at the configured UTC hour (default 05:00 UTC)."""

    hour = int(os.getenv("FLEET_NOTIFICATION_HOUR_UTC", "5"))
    while True:
        now = datetime.utcnow()
        next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep(max((next_run - now).total_seconds(), 1))

        db = SessionLocal()
        try:
            await asyncio.to_thread(run_fleet_notification_checks, db)
        except Exception:
            logger.exception("Fleet notification scheduler run failed")
            db.rollback()
        finally:
            db.close()
