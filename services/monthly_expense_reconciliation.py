"""Read-only reference comparisons. Never supplies authoritative financial values."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import io

from openpyxl import load_workbook

from services.monthly_expense_parser import money, normalize_header

REFERENCE_HEADERS = {
    'gross': {'gross amount'},
    'commission': {'7 commission'},
    'operating_expenses': {'operating expenses', 'total operating expenses', 'total expenses'},
    'net_payable': {'net pay', 'net paid'},
}


def validate_reference_columns(columns, verification):
    if set(columns) - set(REFERENCE_HEADERS):
        raise ValueError('Reference keys must be gross, commission or net_payable')
    if columns and not verification.strip():
        raise ValueError('Manual reference meanings require an explicit verification reason')
    normalized = []
    for key, header in columns.items():
        name = normalize_header(header)
        if name not in REFERENCE_HEADERS[key]:
            raise ValueError(f'Unsupported reference meaning for {key}; intermediate NET PAID columns cannot be final net')
        normalized.append(name)
    if len(set(normalized)) != len(normalized):
        raise ValueError('A manual reference column cannot have two meanings')


def compare_amount(calculated, value):
    """Difference is calculated minus manual; <= KES .01 is rounding-sized only."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return dict(status='missing_reference', manual=None, difference=None)
    try:
        manual = money(value)
    except ValueError:
        return dict(status='invalid_reference', manual=None, difference=None)
    if calculated is None:
        return dict(status='calculation_unavailable', manual=format(manual, '.2f'), difference=None)
    # Retain sub-cent source precision for classifying rounding-sized differences.
    raw = Decimal(str(value).strip().replace(',', ''))
    difference = calculated - manual
    unrounded = calculated - raw
    # Classify on the same cent-rounded values used for display; Excel float dust
    # must not turn a one-cent difference into a material discrepancy.
    status = 'exact_match' if not unrounded else ('rounding_difference' if abs(difference) <= Decimal('.01') else 'material_difference')
    return dict(status=status, manual=format(manual, '.2f'), original_reference=str(value),
                difference=format(difference, '+.2f'), unrounded_difference=str(unrounded))


def reference_analysis(batch):
    decisions = batch['decisions']
    columns = decisions.get('reference_columns', {})
    validate_reference_columns(columns, decisions.get('reference_verification', ''))
    if not columns:
        return {row['source_row']: {key: {'status': 'unverified_reference', 'manual': None, 'difference': None}
                                   for key in REFERENCE_HEADERS} for row in batch['rows']}
    workbook = load_workbook(io.BytesIO(bytes(batch['source_content'])), data_only=False)
    cached = load_workbook(io.BytesIO(bytes(batch['source_content'])), data_only=True)
    try:
        result = {}
        for row in batch['rows']:
            sheet = workbook[row['source_worksheet']]
            output = {}
            for key in REFERENCE_HEADERS:
                if key not in columns:
                    output[key] = {'status': 'unverified_reference', 'manual': None, 'difference': None}
                    continue
                # Original mappings are saved with the report version; no live data lookup.
                matches = [h for h in batch['header_mappings']
                           if h['normalized_header'] == normalize_header(columns[key])]
                if len(matches) != 1:
                    output[key] = {'status': 'missing_reference' if not matches else 'ambiguous_reference',
                                   'manual': None, 'difference': None}
                    continue
                cell = sheet.cell(row['source_row'], matches[0]['column'])
                value = cached[sheet.title][cell.coordinate].value if cell.data_type == 'f' else cell.value
                comparison = compare_amount(row[key], value)
                if cell.data_type == 'f' and value is None:
                    comparison['status'] = 'reference_formula_cache_missing'
                comparison.update(header=columns[key], cell=cell.coordinate,
                                  formula=cell.value if cell.data_type == 'f' else None,
                                  cached_formula=cell.data_type == 'f' and value is not None)
                output[key] = comparison
            result[row['source_row']] = output
        return result
    finally:
        workbook.close()
        cached.close()


def review_historical_adjustments(content: bytes, month: date):
    """Retain original raw bytes plus server-derived date review for confirmation."""
    from services.monthly_expense_dates import retain_source
    return retain_source(content, month)
