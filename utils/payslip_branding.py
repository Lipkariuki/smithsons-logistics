"""Presentation-only branding for payslips, including future imported summaries.

Apply to free-text expense labels/notes when rendering; never mutate source data.
"""

import re


def payslip_text(value: str) -> str:
    return re.sub(r"DHL|Easy Estates", "Smithsons Logistics", value, flags=re.IGNORECASE)
