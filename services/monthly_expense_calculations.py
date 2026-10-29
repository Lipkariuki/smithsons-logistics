"""Decimal calculations for imported monthly summaries, independent of payslips.

Revenue evidence must be supplied by a future adapter reading existing DHL data;
spreadsheet financial summary columns are never used as a revenue source.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

from services.monthly_expense_parser import CENT, ExpenseRow


class RevenueStatus(str, Enum):
    DHL_RECORDS = 'dhl_records'
    VERIFIED_NO_ACTIVITY = 'verified_no_activity'
    MISSING = 'missing'
    INCOMPLETE = 'incomplete'
    UNIMPORTED = 'unimported'


@dataclass(frozen=True)
class RevenueEvidence:
    plate: str
    month: date
    status: RevenueStatus
    gross: Decimal | None = None
    evidence: str = ''  # source snapshot reference or explicit no-activity verification


@dataclass(frozen=True)
class FinancialResult:
    gross: Decimal | None
    operating_expenses: Decimal
    commission_base: Decimal | None
    commission: Decimal | None
    net_payable: Decimal | None
    warnings: tuple[str, ...]
    ready: bool


def calculate_monthly_expenses(row: ExpenseRow, month: date, revenue: RevenueEvidence) -> FinancialResult:
    if month.day != 1 or revenue.month != month or revenue.plate != row.plate:
        raise ValueError('Revenue must match the exact truck and reporting month')
    if not isinstance(revenue.status, RevenueStatus):
        raise ValueError('Explicit revenue status required')
    if not row.ready:
        raise ValueError('Resolve expense validation and header classification before calculation')
    if any(not isinstance(v, Decimal) or not v.is_finite() or v != v.quantize(CENT) for v in row.expenses.values()):
        raise ValueError('All approved expense amounts must be finite Decimals rounded to cents')
    operating = sum(row.expenses.values(), Decimal('0.00'))
    if revenue.status in {RevenueStatus.MISSING, RevenueStatus.INCOMPLETE, RevenueStatus.UNIMPORTED}:
        if revenue.gross is not None:
            raise ValueError('Unverified revenue must not supply a gross amount')
        return FinancialResult(None, operating, None, None, None,
                               ('no_matching_transport_revenue', 'dhl_' + revenue.status.value), False)
    if not revenue.evidence.strip():
        raise ValueError('Verified revenue requires a source or verification reference')
    if not isinstance(revenue.gross, Decimal) or not revenue.gross.is_finite():
        raise ValueError('Verified gross must be a finite Decimal')
    gross = revenue.gross.quantize(CENT, rounding=ROUND_HALF_UP)
    if revenue.status == RevenueStatus.VERIFIED_NO_ACTIVITY and gross != 0:
        raise ValueError('Verified no activity must have zero gross')
    warnings = []
    if revenue.status == RevenueStatus.VERIFIED_NO_ACTIVITY:
        warnings.append('no_matching_transport_revenue_verified_zero')
    if gross == 0:
        warnings.append('zero_revenue')
    base = gross - operating
    commission = (max(base, Decimal('0.00')) * Decimal('0.07')).quantize(CENT, rounding=ROUND_HALF_UP)
    net = base - commission
    if net < 0:
        warnings.append('negative_net_balance_review')
    return FinancialResult(gross, operating, base, commission, net, tuple(warnings), True)
