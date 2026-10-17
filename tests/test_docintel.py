"""Tests for docintel: extraction, validation, review, posting, ledger, pipeline.

All offline and deterministic (no API keys, no network). Synthetic
documents are generated in-process; every pipeline path is tested and
must terminate.
"""

from __future__ import annotations

import pytest

from docintel.documents import (
    DocumentType,
    sample_contract,
    sample_documents,
    sample_expense_receipt,
    sample_invoice,
    sample_purchase_order,
)
from docintel.extraction import ExtractedField, Extractor, LLMExtractor
from docintel.lineage import DocumentLedger
from docintel.pipeline import run_document_pipeline
from docintel.posting import PostingRefused, post_to_erp
from docintel.review import ReviewQueue
from docintel.schemas import FIELD_SCHEMAS, required_fields
from docintel.validation import validate_extraction

# -- documents --------------------------------------------------------------


def test_sample_documents_cover_all_types():
    docs = sample_documents()
    assert len(docs) == 4
    assert {d.doc_type for d in docs} == set(DocumentType)


def test_document_fields():
    doc = sample_invoice()
    assert doc.id == "INV-2041"
    assert doc.doc_type == DocumentType.INVOICE
    assert doc.source_name == "invoice_INV-2041.txt"
    assert doc.pages == 1
    assert "INV-2041" in doc.raw_text


# -- extraction -------------------------------------------------------------


def test_invoice_extracts_all_required_fields():
    fields = Extractor().extract(sample_invoice())
    for name in required_fields(DocumentType.INVOICE):
        assert name in fields, f"missing {name}"
    assert fields["invoice_no"].value == "INV-2041"
    assert fields["invoice_no"].confidence == 1.0
    assert fields["vendor"].value == "Acme Ingredients Co."
    assert fields["date"].value == "2026-10-10"
    assert fields["due_date"].value == "2026-11-09"
    assert fields["currency"].value == "USD"
    assert fields["subtotal"].value == 10710.00
    assert fields["tax"].value == 856.80
    assert fields["total"].value == 11566.80


def test_invoice_line_items_parsed():
    fields = Extractor().extract(sample_invoice())
    items = fields["line_items"].value
    assert len(items) == 2
    assert items[0]["description"] == "Citric acid"
    assert items[0]["amount"] == 10500.00
    assert items[1]["description"] == "Freight"
    assert items[1]["amount"] == 210.00
    assert fields["line_items"].confidence == 1.0


def test_fuzzy_vendor_gets_lower_confidence():
    fields = Extractor().extract(sample_invoice(fuzzy_vendor=True))
    assert fields["vendor"].value == "Acme Ingredients Co."
    assert fields["vendor"].confidence == 0.6
    assert fields["vendor"].confidence < 0.8  # routed to review


def test_po_extraction():
    fields = Extractor().extract(sample_purchase_order())
    assert fields["po_number"].value == "PO-CITRIC-ACID-5000"
    assert fields["supplier"].value == "Acme Ingredients Co."
    assert fields["order_date"].value == "2026-10-11"
    assert fields["total"].value == 11340.00
    assert len(fields["line_items"].value) == 1


def test_contract_extraction():
    fields = Extractor().extract(sample_contract())
    assert fields["agreement_no"].value == "AGR-3310"
    assert fields["party_a"].value == "Ingredion Foods LLC"
    assert fields["party_b"].value == "Acme Ingredients Co."
    assert fields["effective_date"].value == "2026-01-01"
    assert fields["term_months"].value == 24
    assert fields["value"].value == 250000.00
    assert fields["currency"].value == "USD"
    assert len(fields["key_clauses"].value) == 3


def test_receipt_extraction():
    fields = Extractor().extract(sample_expense_receipt())
    assert fields["receipt_no"].value == "RCP-88213"
    assert fields["merchant"].value == "Delta Airlines"
    assert fields["date"].value == "2026-09-28"
    assert fields["amount"].value == 486.20
    assert fields["currency"].value == "USD"


def test_extracted_field_carries_source_snippet():
    fields = Extractor().extract(sample_invoice())
    snippet = fields["invoice_no"].source_snippet
    assert "INV-2041" in snippet


def test_llm_extractor_refuses_without_key(monkeypatch):
    monkeypatch.delenv("AZURE_DOCINTEL_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(NotImplementedError):
        LLMExtractor().extract(sample_invoice())


# -- validation -------------------------------------------------------------


def test_clean_invoice_has_no_issues():
    fields = Extractor().extract(sample_invoice())
    issues = validate_extraction(DocumentType.INVOICE, fields)
    assert issues == []


def test_total_mismatch_is_error():
    fields = Extractor().extract(sample_invoice(mismatch=True))
    issues = validate_extraction(DocumentType.INVOICE, fields)
    total_errors = [i for i in issues if i.field == "total" and i.severity == "error"]
    assert len(total_errors) == 1
    assert "11,000.00" in total_errors[0].message


def test_missing_required_field_is_error():
    fields = Extractor().extract(sample_invoice())
    del fields["vendor"]
    issues = validate_extraction(DocumentType.INVOICE, fields)
    assert any(
        i.field == "vendor" and i.severity == "error" and "missing" in i.message
        for i in issues
    )


def test_bad_date_is_error():
    fields = Extractor().extract(sample_invoice())
    fields["date"] = ExtractedField("date", "10/10/2026", 1.0, "bad")
    issues = validate_extraction(DocumentType.INVOICE, fields)
    assert any(i.field == "date" and i.severity == "error" for i in issues)


def test_bad_currency_is_error():
    fields = Extractor().extract(sample_invoice())
    fields["currency"] = ExtractedField("currency", "US", 1.0, "bad")
    issues = validate_extraction(DocumentType.INVOICE, fields)
    assert any(i.field == "currency" and i.severity == "error" for i in issues)


def test_line_item_sum_mismatch_is_error():
    fields = Extractor().extract(sample_invoice())
    fields["line_items"].value[0]["amount"] = 9999.00  # corrupt one row
    issues = validate_extraction(DocumentType.INVOICE, fields)
    assert any(i.field == "subtotal" and i.severity == "error" for i in issues)


def test_bad_invoice_number_pattern_is_error():
    fields = Extractor().extract(sample_invoice())
    fields["invoice_no"] = ExtractedField("invoice_no", "XYZ", 1.0, "bad")
    issues = validate_extraction(DocumentType.INVOICE, fields)
    assert any(i.field == "invoice_no" and i.severity == "error" for i in issues)


def test_clean_contract_and_receipt_validate():
    assert validate_extraction(DocumentType.CONTRACT, Extractor().extract(sample_contract())) == []
    assert (
        validate_extraction(DocumentType.EXPENSE_RECEIPT, Extractor().extract(sample_expense_receipt()))
        == []
    )


# -- review -----------------------------------------------------------------


def test_low_confidence_field_routed_to_review():
    fields = Extractor().extract(sample_invoice(fuzzy_vendor=True))
    issues = validate_extraction(DocumentType.INVOICE, fields)
    queue = ReviewQueue()
    pending = queue.route(fields, issues)
    assert [i.field_name for i in pending] == ["vendor"]
    assert "low confidence" in pending[0].reason


def test_validation_error_field_routed_to_review():
    fields = Extractor().extract(sample_invoice(mismatch=True))
    issues = validate_extraction(DocumentType.INVOICE, fields)
    queue = ReviewQueue()
    pending = queue.route(fields, issues)
    assert "total" in [i.field_name for i in pending]


def test_submit_review_records_correction():
    fields = Extractor().extract(sample_invoice(fuzzy_vendor=True))
    queue = ReviewQueue()
    queue.route(fields, [])
    item = queue.submit_review("vendor", "Acme Ingredients Co.", "jagadeesh")
    assert item.status == "corrected"
    assert item.reviewer == "jagadeesh"
    assert queue.corrected_fields() == {"vendor": "Acme Ingredients Co."}
    assert queue.is_clear()


def test_submit_review_unknown_field_raises():
    queue = ReviewQueue()
    with pytest.raises(KeyError):
        queue.submit_review("nope", "x", "jagadeesh")


def test_review_stats_reports_correction_rate():
    fields = Extractor().extract(sample_invoice(fuzzy_vendor=True))
    queue = ReviewQueue()
    queue.route(fields, [])
    queue.submit_review("vendor", "Acme Ingredients Co.", "jagadeesh")
    stats = queue.review_stats()
    assert stats["vendor"]["routed"] == 1.0
    assert stats["vendor"]["corrected"] == 1.0
    assert stats["vendor"]["correction_rate"] == 1.0


# -- posting ----------------------------------------------------------------


def test_posting_refused_with_unresolved_errors():
    fields = Extractor().extract(sample_invoice(mismatch=True))
    issues = validate_extraction(DocumentType.INVOICE, fields)
    with pytest.raises(PostingRefused) as exc:
        post_to_erp("INV-2041", DocumentType.INVOICE, fields, issues)
    assert "unresolved error" in str(exc.value)


def test_posting_succeeds_when_clean():
    fields = Extractor().extract(sample_invoice())
    issues = validate_extraction(DocumentType.INVOICE, fields)
    record = post_to_erp("INV-2041", DocumentType.INVOICE, fields, issues)
    assert record.status == "posted"
    assert record.erp_ref == "ERP-INV-2041"  # deterministic
    assert record.total_posted == 11566.80
    assert "T" in record.posted_at


def test_warnings_do_not_block_posting():
    from docintel.validation import ValidationIssue

    fields = Extractor().extract(sample_invoice())
    issues = [ValidationIssue("vendor", "warning", "unusual vendor name")]
    record = post_to_erp("INV-2041", DocumentType.INVOICE, fields, issues)
    assert record.status == "posted"


# -- ledger -----------------------------------------------------------------


def test_ledger_chain_verifies():
    ledger = DocumentLedger()
    ledger.record("ingested", "INV-2041", {"source": "x.txt"})
    ledger.record("extracted", "INV-2041", {"fields": 9})
    ledger.record("posted", "INV-2041", {"erp_ref": "ERP-INV-2041"})
    assert ledger.verify_chain() is True
    assert ledger.stages_for("INV-2041") == ["ingested", "extracted", "posted"]


def test_ledger_tamper_detection():
    ledger = DocumentLedger()
    ledger.record("ingested", "INV-2041", {"source": "x.txt"})
    ledger.record("posted", "INV-2041", {"erp_ref": "ERP-INV-2041"})
    ledger._entries[0]["details"]["source"] = "forged.txt"  # tamper
    assert ledger.verify_chain() is False


def test_ledger_export_jsonl():
    ledger = DocumentLedger()
    ledger.record("ingested", "INV-2041")
    lines = ledger.export_jsonl().strip().splitlines()
    assert len(lines) == 1
    assert '"stage": "ingested"' in lines[0]


# -- pipeline ---------------------------------------------------------------


def test_pipeline_happy_path_posts():
    state = run_document_pipeline(sample_invoice())
    assert state["outcome"] == "posted"
    assert state["erp_record"]["erp_ref"] == "ERP-INV-2041"
    assert state["erp_record"]["total_posted"] == 11566.80
    assert state["ledger"].verify_chain() is True
    assert "held" not in str(state.get("hold_reason", ""))


def test_pipeline_review_path_posts_after_correction():
    state = run_document_pipeline(
        sample_invoice(mismatch=True), corrections={"total": 11566.80}
    )
    assert state["outcome"] == "posted"
    assert state["applied_corrections"] == ["total"]
    assert state["erp_record"]["total_posted"] == 11566.80
    assert state["ledger"].verify_chain() is True


def test_pipeline_held_when_review_does_not_resolve():
    state = run_document_pipeline(sample_invoice(mismatch=True))
    assert state["outcome"] == "held"
    assert "hold_reason" in state
    assert "erp_record" not in state
    assert state["ledger"].verify_chain() is True


def test_pipeline_fuzzy_vendor_goes_through_review():
    state = run_document_pipeline(
        sample_invoice(fuzzy_vendor=True),
        corrections={"vendor": "Acme Ingredients Co."},
    )
    assert state["outcome"] == "posted"
    assert state["applied_corrections"] == ["vendor"]


def test_pipeline_records_every_stage_in_ledger():
    state = run_document_pipeline(sample_invoice(mismatch=True))
    stages = state["ledger"].stages_for("INV-2041")
    assert stages == [
        "ingested",
        "extracted",
        "validated",
        "review_routed",
        "reviewed",
        "revalidated",
        "held",
    ]


def test_pipeline_all_doc_types_terminate():
    for doc in sample_documents():
        state = run_document_pipeline(doc)
        assert state["outcome"] in ("posted", "held")
        assert state["ledger"].verify_chain() is True


# -- schemas ----------------------------------------------------------------


def test_schemas_have_required_fields():
    assert "invoice_no" in required_fields(DocumentType.INVOICE)
    assert "po_number" in required_fields(DocumentType.PURCHASE_ORDER)
    assert "agreement_no" in required_fields(DocumentType.CONTRACT)
    assert "receipt_no" in required_fields(DocumentType.EXPENSE_RECEIPT)
    assert len(FIELD_SCHEMAS) == 4
