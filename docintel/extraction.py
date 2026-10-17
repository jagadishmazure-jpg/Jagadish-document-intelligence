"""Deterministic heuristic extraction from document text.

``Extractor`` applies ordered regex/keyword rules per document type and
returns ``ExtractedField`` values with a confidence score:

- 1.0 — exact labeled hit (``Invoice No: INV-2041``)
- 0.7 — fuzzy fallback (the bare pattern ``INV-2041`` with no label)
- 0.5 — partial/garbled hit (a line-item row that does not fully parse)

``LLMExtractor`` shares the interface and documents the production path
(Azure Document Intelligence / GPT-4o vision); it refuses to run without
credentials so the offline demo never silently pretends to call a model.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from docintel.documents import Document, DocumentType


@dataclass
class ExtractedField:
    name: str
    value: Any
    confidence: float  # 0.0 - 1.0
    source_snippet: str


def _money(text: str) -> float:
    return float(text.replace("$", "").replace(",", "").strip())


def _first_match(
    text: str, patterns: List[Tuple[str, float]], flags: int = 0
) -> Optional[Tuple[str, float, str]]:
    """Return (value, confidence, matched_line) for the first matching pattern."""
    for pattern, confidence in patterns:
        match = re.search(pattern, text, flags)
        if match:
            line = next(
                (ln.strip() for ln in text.splitlines() if match.group(0) in ln),
                match.group(0),
            )
            return match.group(1).strip(), confidence, line
    return None


def _extract_money_field(
    text: str, label: str
) -> Optional[Tuple[float, float, str]]:
    hit = _first_match(
        text,
        [
            (rf"^{label}[^:\n]*:\s*\$?([\d,]+\.\d{{2}})", 1.0),
            (rf"{label}[^:\n]*:\s*\$?([\d,]+\.\d{{2}})", 0.7),
        ],
        re.MULTILINE | re.IGNORECASE,
    )
    if hit is None:
        return None
    value, confidence, snippet = hit
    return _money(value), confidence, snippet


def _extract_line_items(text: str) -> Tuple[List[Dict[str, Any]], float, str]:
    """Parse the ``Line Items:`` section; rows look like::

        - Citric acid | 5000 kg @ $2.10/kg | $10,500.00
    """
    section = re.search(
        r"Line Items:\s*\n((?:- .+\n?)+)", text, re.IGNORECASE
    )
    if not section:
        return [], 0.0, ""
    items: List[Dict[str, Any]] = []
    worst = 1.0
    for line in section.group(1).strip().splitlines():
        line = line.strip()
        row = re.match(r"-\s*(.+?)\s*\|\s*(.+?)\s*\|\s*\$?([\d,]+\.\d{2})", line)
        if row:
            items.append(
                {
                    "description": row.group(1).strip(),
                    "quantity": row.group(2).strip(),
                    "amount": _money(row.group(3)),
                }
            )
        else:
            # Partial row: keep what we can, at reduced confidence.
            items.append({"description": line.lstrip("- ").strip(), "quantity": "", "amount": 0.0})
            worst = min(worst, 0.5)
    return items, worst, section.group(0).strip()


class Extractor:
    """Rule-based extractor: deterministic, offline, no API keys."""

    def extract(self, document: Document) -> Dict[str, ExtractedField]:
        handler = {
            DocumentType.INVOICE: self._extract_invoice,
            DocumentType.PURCHASE_ORDER: self._extract_po,
            DocumentType.CONTRACT: self._extract_contract,
            DocumentType.EXPENSE_RECEIPT: self._extract_receipt,
        }[document.doc_type]
        return handler(document.raw_text)

    # -- shared helpers ---------------------------------------------------

    def _date(self, text: str, label: str) -> Optional[ExtractedField]:
        hit = _first_match(
            text,
            [
                (rf"^{label}:\s*(\d{{4}}-\d{{2}}-\d{{2}})", 1.0),
                (r"(\d{4}-\d{2}-\d{2})", 0.7),
            ],
            re.MULTILINE | re.IGNORECASE,
        )
        if hit is None:
            return None
        value, confidence, snippet = hit
        return ExtractedField(label.lower().replace(" ", "_"), value, confidence, snippet)

    def _money_field(
        self, text: str, name: str, label: str
    ) -> Optional[ExtractedField]:
        hit = _extract_money_field(text, label)
        if hit is None:
            return None
        value, confidence, snippet = hit
        return ExtractedField(name, value, confidence, snippet)

    def _labeled(
        self, text: str, name: str, label: str, fuzzy_label: Optional[str] = None
    ) -> Optional[ExtractedField]:
        patterns: List[Tuple[str, float]] = [(rf"^{label}:\s*(.+)$", 1.0)]
        if fuzzy_label:
            patterns.append((rf"(?i){fuzzy_label}", 0.6))
        hit = _first_match(text, patterns, re.MULTILINE)
        if hit is None:
            return None
        value, confidence, snippet = hit
        return ExtractedField(name, value, confidence, snippet)

    # -- per-type rules ----------------------------------------------------

    def _extract_invoice(self, text: str) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}
        hit = _first_match(
            text,
            [(r"^Invoice No:\s*(\S+)", 1.0), (r"\b(INV-\d+)\b", 0.7)],
            re.MULTILINE,
        )
        if hit:
            fields["invoice_no"] = ExtractedField("invoice_no", *hit)
        vendor = self._labeled(text, "vendor", "Vendor")
        # Fuzzy vendor fallback: a line mentioning "(vendor)" names the vendor.
        # Handled here (not in _labeled) because the pattern has no capture group.
        if vendor is None:
            fuzzy = re.search(r"(?im)^.*\(vendor\).*$", text)
            if fuzzy:
                line = fuzzy.group(0).strip()
                name = re.sub(r"(?i).*at\s+|\s*\(vendor\).*", "", line).strip()
                vendor = ExtractedField("vendor", name or line, 0.6, line)
        if vendor:
            fields["vendor"] = vendor
        for name, label in (("date", "Invoice Date"), ("due_date", "Due Date")):
            found = self._date(text, label)
            if found:
                fields[name] = found
        cur = _first_match(
            text,
            [(r"^Currency:\s*([A-Z]{3})", 1.0), (r"\b([A-Z]{3})\b", 0.6)],
            re.MULTILINE,
        )
        if cur:
            fields["currency"] = ExtractedField("currency", *cur)
        items, conf, snippet = _extract_line_items(text)
        if items:
            fields["line_items"] = ExtractedField("line_items", items, conf, snippet)
        for name, label in (
            ("subtotal", "Subtotal"),
            ("tax", "Tax"),
            ("total", "Total Due"),
        ):
            found = self._money_field(text, name, label)
            if found:
                fields[name] = found
        if "total" not in fields:  # "Total:" without "Due"
            found = self._money_field(text, "total", "Total")
            if found:
                fields["total"] = found
        return fields

    def _extract_po(self, text: str) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}
        hit = _first_match(
            text,
            [(r"^PO Number:\s*(\S+)", 1.0), (r"\b(PO-[A-Z0-9-]+)\b", 0.7)],
            re.MULTILINE,
        )
        if hit:
            fields["po_number"] = ExtractedField("po_number", *hit)
        supplier = self._labeled(text, "supplier", "Supplier")
        if supplier:
            fields["supplier"] = supplier
        for name, label in (("order_date", "Order Date"), ("delivery_date", "Delivery Date")):
            found = self._date(text, label)
            if found:
                fields[name] = found
        cur = _first_match(text, [(r"^Currency:\s*([A-Z]{3})", 1.0)], re.MULTILINE)
        if cur:
            fields["currency"] = ExtractedField("currency", *cur)
        items, conf, snippet = _extract_line_items(text)
        if items:
            fields["line_items"] = ExtractedField("line_items", items, conf, snippet)
        for name, label in (("subtotal", "Subtotal"), ("tax", "Tax"), ("total", "Total")):
            found = self._money_field(text, name, label)
            if found:
                fields[name] = found
        return fields

    def _extract_contract(self, text: str) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}
        hit = _first_match(
            text,
            [(r"^Agreement No:\s*(\S+)", 1.0), (r"\b(AGR-\d+)\b", 0.7)],
            re.MULTILINE,
        )
        if hit:
            fields["agreement_no"] = ExtractedField("agreement_no", *hit)
        for name, label in (("party_a", "Party A"), ("party_b", "Party B")):
            found = self._labeled(text, name, label)
            if found:
                fields[name] = found
        found = self._date(text, "Effective Date")
        if found:
            fields["effective_date"] = found
        term = _first_match(
            text, [(r"^Term:\s*(\d+)\s*months?", 1.0)], re.MULTILINE | re.IGNORECASE
        )
        if term:
            value, confidence, snippet = term
            fields["term_months"] = ExtractedField("term_months", int(value), confidence, snippet)
        value_hit = _first_match(
            text,
            [(r"^Contract Value:\s*\$?([\d,]+\.\d{2})", 1.0)],
            re.MULTILINE,
        )
        if value_hit:
            value, confidence, snippet = value_hit
            fields["value"] = ExtractedField("value", _money(value), confidence, snippet)
        cur = _first_match(
            text, [(r"Contract Value:[^\n]*\b([A-Z]{3})\b", 0.8)], re.MULTILINE
        )
        if cur:
            fields["currency"] = ExtractedField("currency", *cur)
        clauses = _first_match(text, [(r"^Key Clauses:\s*(.+)$", 1.0)], re.MULTILINE)
        if clauses:
            value, confidence, snippet = clauses
            fields["key_clauses"] = ExtractedField(
                "key_clauses",
                [c.strip() for c in value.split(";") if c.strip()],
                confidence,
                snippet,
            )
        return fields

    def _extract_receipt(self, text: str) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}
        hit = _first_match(
            text,
            [(r"^Receipt No:\s*(\S+)", 1.0), (r"\b(RCP-\d+)\b", 0.7)],
            re.MULTILINE,
        )
        if hit:
            fields["receipt_no"] = ExtractedField("receipt_no", *hit)
        for name, label in (("merchant", "Merchant"), ("category", "Category")):
            found = self._labeled(text, name, label)
            if found:
                fields[name] = found
        found = self._date(text, "Date")
        if found:
            fields["date"] = found
        amount = _first_match(
            text, [(r"^Amount:\s*\$?([\d,]+\.\d{2})", 1.0)], re.MULTILINE
        )
        if amount:
            value, confidence, snippet = amount
            fields["amount"] = ExtractedField("amount", _money(value), confidence, snippet)
        cur = _first_match(text, [(r"^Amount:[^\n]*\b([A-Z]{3})\b", 0.8)], re.MULTILINE)
        if cur:
            fields["currency"] = ExtractedField("currency", *cur)
        return fields


class LLMExtractor(Extractor):
    """Production-path extractor stub: same interface, model-backed.

    In production this delegates to Azure Document Intelligence
    (layout + prebuilt invoice/receipt models) with GPT-4o vision as the
    fallback for unstructured documents. It refuses to run without
    credentials so offline tests never silently pretend to call a model.
    """

    def extract(self, document: Document) -> Dict[str, ExtractedField]:  # noqa: D102
        key = os.environ.get("AZURE_DOCINTEL_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise NotImplementedError(
                "LLMExtractor requires AZURE_DOCINTEL_KEY or OPENAI_API_KEY; "
                "use Extractor for offline deterministic extraction."
            )
        raise NotImplementedError(
            "Model-backed extraction is a deployment-time integration; "
            "wire your Document Intelligence client here."
        )
