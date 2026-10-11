"""Validation of extracted fields: required presence, formats, consistency.

Checks:

- every required schema field is present and non-empty;
- dates are valid ISO ``YYYY-MM-DD`` calendar dates;
- currency codes are 3-letter ISO codes;
- document numbers match their expected patterns;
- money fields are non-negative;
- cross-field consistency: line-item amounts sum to the subtotal, and
  subtotal + tax equals the total, each within a 1% tolerance.

Returns ``ValidationIssue`` entries with ``error`` or ``warning``
severity. Warnings never block ERP posting; errors do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from docintel.documents import DocumentType
from docintel.extraction import ExtractedField
from docintel.schemas import FIELD_SCHEMAS

#: 1% tolerance for money cross-checks.
TOLERANCE = 0.01

ID_PATTERNS = {
    "invoice_no": r"^INV-\d+$",
    "po_number": r"^PO-[A-Z0-9-]+$",
    "agreement_no": r"^AGR-\d+$",
    "receipt_no": r"^RCP-\d+$",
}


@dataclass
class ValidationIssue:
    field: str
    severity: str  # "error" | "warning"
    message: str


def _is_valid_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_extraction(
    doc_type: DocumentType, fields: Dict[str, ExtractedField]
) -> List[ValidationIssue]:
    """Validate extracted fields against the schema for ``doc_type``."""
    issues: List[ValidationIssue] = []
    schema = {f.name: f for f in FIELD_SCHEMAS[doc_type]}

    # 1. Required-field presence.
    for name, spec in schema.items():
        found = fields.get(name)
        if not spec.required:
            continue
        if found is None or found.value in (None, "", []):
            issues.append(
                ValidationIssue(name, "error", f"required field {name!r} is missing")
            )

    # 2. Format checks on present fields.
    for name, found in fields.items():
        spec = schema.get(name)
        if spec is None:
            issues.append(
                ValidationIssue(name, "warning", f"field {name!r} not in schema")
            )
            continue
        value = found.value
        if spec.value_type == "date" and not _is_valid_date(value):
            issues.append(
                ValidationIssue(name, "error", f"{name!r} is not a valid YYYY-MM-DD date: {value!r}")
            )
        elif spec.value_type == "currency" and not (
            isinstance(value, str) and re.fullmatch(r"[A-Z]{3}", value)
        ):
            issues.append(
                ValidationIssue(name, "error", f"{name!r} is not a 3-letter ISO code: {value!r}")
            )
        elif spec.value_type == "money" and not (
            isinstance(value, (int, float)) and value >= 0
        ):
            issues.append(
                ValidationIssue(name, "error", f"{name!r} must be a non-negative amount: {value!r}")
            )
        elif spec.value_type == "integer" and not (
            isinstance(value, int) and 1 <= value <= 120
        ):
            issues.append(
                ValidationIssue(name, "error", f"{name!r} must be an integer 1..120: {value!r}")
            )
        if name in ID_PATTERNS and isinstance(value, str):
            if not re.fullmatch(ID_PATTERNS[name], value):
                issues.append(
                    ValidationIssue(
                        name, "error", f"{name!r} does not match {ID_PATTERNS[name]}: {value!r}"
                    )
                )

    # 3. Cross-field money consistency (invoices and purchase orders).
    if doc_type in (DocumentType.INVOICE, DocumentType.PURCHASE_ORDER):
        items = fields.get("line_items")
        subtotal = fields.get("subtotal")
        tax = fields.get("tax")
        total = fields.get("total")
        if items and subtotal and isinstance(subtotal.value, (int, float)):
            line_sum = sum(i.get("amount", 0.0) for i in items.value)
            if abs(line_sum - subtotal.value) > TOLERANCE * max(subtotal.value, 1.0):
                issues.append(
                    ValidationIssue(
                        "subtotal",
                        "error",
                        f"line items sum to {line_sum:,.2f} but subtotal is {subtotal.value:,.2f}",
                    )
                )
        if subtotal and total and isinstance(subtotal.value, (int, float)) and isinstance(
            total.value, (int, float)
        ):
            expected = subtotal.value + (
                tax.value if tax and isinstance(tax.value, (int, float)) else 0.0
            )
            if abs(expected - total.value) > TOLERANCE * max(total.value, 1.0):
                issues.append(
                    ValidationIssue(
                        "total",
                        "error",
                        f"subtotal + tax = {expected:,.2f} but total is {total.value:,.2f}",
                    )
                )

    return issues
