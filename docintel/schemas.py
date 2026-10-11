"""Per-document-type field schemas: what extraction must produce.

Each field declares its name, whether it is required, its value type,
and a validation hint consumed by ``docintel.validation``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from docintel.documents import DocumentType


@dataclass(frozen=True)
class FieldSchema:
    name: str
    required: bool
    value_type: str  # "string" | "date" | "money" | "currency" | "line_items" | "integer" | "clauses"
    hint: str


INVOICE_FIELDS: List[FieldSchema] = [
    FieldSchema("invoice_no", True, "string", "pattern ^INV-\\d+$"),
    FieldSchema("vendor", True, "string", "non-empty"),
    FieldSchema("date", True, "date", "ISO YYYY-MM-DD"),
    FieldSchema("due_date", False, "date", "ISO YYYY-MM-DD"),
    FieldSchema("currency", True, "currency", "3-letter ISO code"),
    FieldSchema("line_items", True, "line_items", "each item has description, quantity, amount"),
    FieldSchema("subtotal", True, "money", ">= 0"),
    FieldSchema("tax", False, "money", ">= 0"),
    FieldSchema("total", True, "money", "≈ subtotal + tax within 1%"),
]

PO_FIELDS: List[FieldSchema] = [
    FieldSchema("po_number", True, "string", "pattern ^PO-[A-Z0-9-]+$"),
    FieldSchema("supplier", True, "string", "non-empty"),
    FieldSchema("order_date", True, "date", "ISO YYYY-MM-DD"),
    FieldSchema("delivery_date", False, "date", "ISO YYYY-MM-DD"),
    FieldSchema("currency", True, "currency", "3-letter ISO code"),
    FieldSchema("line_items", True, "line_items", "each item has description, quantity, amount"),
    FieldSchema("subtotal", True, "money", ">= 0"),
    FieldSchema("tax", False, "money", ">= 0"),
    FieldSchema("total", True, "money", "≈ subtotal + tax within 1%"),
]

CONTRACT_FIELDS: List[FieldSchema] = [
    FieldSchema("agreement_no", True, "string", "pattern ^AGR-\\d+$"),
    FieldSchema("party_a", True, "string", "non-empty"),
    FieldSchema("party_b", True, "string", "non-empty"),
    FieldSchema("effective_date", True, "date", "ISO YYYY-MM-DD"),
    FieldSchema("term_months", True, "integer", "1..120"),
    FieldSchema("value", True, "money", ">= 0"),
    FieldSchema("currency", True, "currency", "3-letter ISO code"),
    FieldSchema("key_clauses", False, "clauses", "semicolon-separated list"),
]

RECEIPT_FIELDS: List[FieldSchema] = [
    FieldSchema("receipt_no", True, "string", "pattern ^RCP-\\d+$"),
    FieldSchema("merchant", True, "string", "non-empty"),
    FieldSchema("date", True, "date", "ISO YYYY-MM-DD"),
    FieldSchema("category", False, "string", "non-empty"),
    FieldSchema("amount", True, "money", ">= 0"),
    FieldSchema("currency", True, "currency", "3-letter ISO code"),
]

FIELD_SCHEMAS: Dict[DocumentType, List[FieldSchema]] = {
    DocumentType.INVOICE: INVOICE_FIELDS,
    DocumentType.PURCHASE_ORDER: PO_FIELDS,
    DocumentType.CONTRACT: CONTRACT_FIELDS,
    DocumentType.EXPENSE_RECEIPT: RECEIPT_FIELDS,
}


def required_fields(doc_type: DocumentType) -> List[str]:
    """Names of required fields for a document type."""
    return [f.name for f in FIELD_SCHEMAS[doc_type] if f.required]
