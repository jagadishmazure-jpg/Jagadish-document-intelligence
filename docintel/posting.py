"""ERP posting: the final, guarded step of the paper-to-payment flow.

Posting is refused unless every validation *error* is resolved —
warnings never block. The ERP reference is deterministic
(``ERP-<doc-id>``) so tests and replays are stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List

from docintel.documents import DocumentType
from docintel.extraction import ExtractedField
from docintel.validation import ValidationIssue


class PostingRefused(Exception):
    """Raised when unresolved validation errors block ERP posting."""


@dataclass
class ERPRecord:
    doc_id: str
    erp_ref: str
    posted_at: str
    status: str  # "posted"
    doc_type: str
    total_posted: float | None = None


def _total_for(doc_type: DocumentType, fields: Dict[str, ExtractedField]) -> float | None:
    key = "total" if doc_type in (DocumentType.INVOICE, DocumentType.PURCHASE_ORDER) else None
    if key is None:
        key = "amount" if doc_type == DocumentType.EXPENSE_RECEIPT else "value"
    found = fields.get(key)
    if found and isinstance(found.value, (int, float)):
        return float(found.value)
    return None


def post_to_erp(
    doc_id: str,
    doc_type: DocumentType,
    fields: Dict[str, ExtractedField],
    issues: List[ValidationIssue],
) -> ERPRecord:
    """Post a validated document to ERP.

    Raises ``PostingRefused`` when any unresolved *error* remains.
    Returns the posted record on success.
    """
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        summary = "; ".join(f"{e.field}: {e.message}" for e in errors)
        raise PostingRefused(
            f"cannot post {doc_id}: {len(errors)} unresolved error(s): {summary}"
        )
    return ERPRecord(
        doc_id=doc_id,
        erp_ref=f"ERP-{doc_id}",
        posted_at=datetime.now(timezone.utc).isoformat(),
        status="posted",
        doc_type=doc_type.value,
        total_posted=_total_for(doc_type, fields),
    )
