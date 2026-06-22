from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FleetVehicleCreate(BaseModel):
    registration_number: str = Field(min_length=1, max_length=50)
    owner_id: Optional[int] = None
    size: Optional[str] = None
    make_model: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_policy_number: Optional[str] = None
    insurance_expiry_date: Optional[date] = None
    inspection_expiry_date: Optional[date] = None
    service_interval_km: Optional[int] = Field(default=None, ge=1)
    current_mileage: Optional[int] = Field(default=None, ge=0)
    last_service_date: Optional[date] = None
    last_service_mileage: Optional[int] = Field(default=None, ge=0)
    next_service_due_mileage: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def derive_next_service_due(self):
        if (
            self.next_service_due_mileage is None
            and self.last_service_mileage is not None
            and self.service_interval_km is not None
        ):
            self.next_service_due_mileage = self.last_service_mileage + self.service_interval_km
        return self


class FleetVehicleUpdate(BaseModel):
    registration_number: Optional[str] = Field(default=None, min_length=1, max_length=50)
    owner_id: Optional[int] = None
    size: Optional[str] = None
    make_model: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_policy_number: Optional[str] = None
    insurance_expiry_date: Optional[date] = None
    inspection_expiry_date: Optional[date] = None
    service_interval_km: Optional[int] = Field(default=None, ge=1)
    current_mileage: Optional[int] = Field(default=None, ge=0)
    last_service_date: Optional[date] = None
    last_service_mileage: Optional[int] = Field(default=None, ge=0)
    next_service_due_mileage: Optional[int] = Field(default=None, ge=0)


class FleetVehicleOut(BaseModel):
    id: int
    registration_number: str
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    size: Optional[str] = None
    make_model: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_policy_number: Optional[str] = None
    insurance_expiry_date: Optional[date] = None
    inspection_expiry_date: Optional[date] = None
    service_interval_km: Optional[int] = None
    current_mileage: Optional[int] = None
    last_service_date: Optional[date] = None
    last_service_mileage: Optional[int] = None
    next_service_due_mileage: Optional[int] = None
    service_km_remaining: Optional[int] = None


class FleetDriverComplianceUpdate(BaseModel):
    driver_license_number: Optional[str] = None
    driver_license_expiry_date: Optional[date] = None


class FleetDriverOut(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    driver_license_number: Optional[str] = None
    driver_license_expiry_date: Optional[date] = None


class FleetNotificationOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    notification_type: str
    reminder_threshold: str
    due_date: Optional[date] = None
    due_mileage: Optional[int] = None
    recipient: str
    message: str
    status: str
    provider_response: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class FleetDashboardOut(BaseModel):
    insurance_expiring_soon: list[FleetVehicleOut]
    inspections_expiring_soon: list[FleetVehicleOut]
    vehicles_due_for_service: list[FleetVehicleOut]
    driver_licenses_expiring_soon: list[FleetDriverOut]
    counts: dict[str, int]


class FleetNotificationRunOut(BaseModel):
    checked: int
    sent: int
    skipped: int
    failed: int
