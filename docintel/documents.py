"""Business documents and synthetic sample generation.

Extraction works on plain text (no PDFs needed for the demo): each
``Document`` carries ``raw_text`` plus metadata. ``sample_documents()``
generates realistic synthetic documents for every supported type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List


class DocumentType(str, Enum):
    INVOICE = "invoice"
    PURCHASE_ORDER = "purchase_order"
    CONTRACT = "contract"
    EXPENSE_RECEIPT = "expense_receipt"


@dataclass
class Document:
    """A business document to process."""

    id: str
    doc_type: DocumentType
    source_name: str
    raw_text: str
    pages: int = 1
    metadata: Dict[str, str] = field(default_factory=dict)


def sample_invoice(*, mismatch: bool = False, fuzzy_vendor: bool = False) -> Document:
    """Synthetic vendor invoice.

    ``mismatch`` corrupts the total so cross-field validation fails.
    ``fuzzy_vendor`` writes the vendor line in a non-standard format so
    extraction falls back to a lower-confidence rule.
    """
    vendor_line = "Vendor: Acme Ingredients Co."
    if fuzzy_vendor:
        vendor_line = "Billed by our friends at Acme Ingredients Co. (vendor)"
    total = "$11,566.80"
    if mismatch:
        total = "$11,000.00"  # does not equal subtotal + tax
    text = f"""INVOICE
Invoice No: INV-2041
{vendor_line}
Invoice Date: 2026-10-10
Due Date: 2026-11-09
Currency: USD

Line Items:
- Citric acid | 5000 kg @ $2.10/kg | $10,500.00
- Freight | 1 lot @ $210.00 | $210.00

Subtotal: $10,710.00
Tax (8%): $856.80
Total Due: {total}
"""
    return Document(
        id="INV-2041",
        doc_type=DocumentType.INVOICE,
        source_name="invoice_INV-2041.txt",
        raw_text=text,
    )


def sample_purchase_order() -> Document:
    text = """PURCHASE ORDER
PO Number: PO-CITRIC-ACID-5000
Supplier: Acme Ingredients Co.
Order Date: 2026-10-11
Delivery Date: 2026-10-18
Currency: USD

Line Items:
- Citric acid | 5000 kg @ $2.10/kg | $10,500.00

Subtotal: $10,500.00
Tax (8%): $840.00
Total: $11,340.00
"""
    return Document(
        id="PO-CITRIC-ACID-5000",
        doc_type=DocumentType.PURCHASE_ORDER,
        source_name="po_PO-CITRIC-ACID-5000.txt",
        raw_text=text,
    )


def sample_contract() -> Document:
    text = """SERVICES AGREEMENT
Agreement No: AGR-3310
Party A: Ingredion Foods LLC
Party B: Acme Ingredients Co.
Effective Date: 2026-01-01
Term: 24 months
Contract Value: $250,000.00 USD
Key Clauses: confidentiality; termination for convenience with 90 days notice; indemnification
"""
    return Document(
        id="AGR-3310",
        doc_type=DocumentType.CONTRACT,
        source_name="contract_AGR-3310.txt",
        raw_text=text,
    )


def sample_expense_receipt() -> Document:
    text = """EXPENSE RECEIPT
Receipt No: RCP-88213
Merchant: Delta Airlines
Date: 2026-09-28
Category: Travel - Airfare
Amount: $486.20 USD
"""
    return Document(
        id="RCP-88213",
        doc_type=DocumentType.EXPENSE_RECEIPT,
        source_name="receipt_RCP-88213.txt",
        raw_text=text,
    )


def sample_documents() -> List[Document]:
    """One synthetic document per supported type."""
    return [
        sample_invoice(),
        sample_purchase_order(),
        sample_contract(),
        sample_expense_receipt(),
    ]
