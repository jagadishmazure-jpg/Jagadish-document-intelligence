# Jagadish Document Intelligence

Enterprise intelligent document processing (IDP): extract structured data from business documents, validate it, route low-confidence fields to human review, and post clean records to ERP. The **paper-to-payment** flow.

Enterprises drown in PDFs — invoices, purchase orders, contracts, receipts. This project shows how that unstructured intake becomes governed, auditable ERP postings with a human-in-the-loop safety net.

![CI](https://github.com/jagadishmazure-jpg/Jagadish-document-intelligence/actions/workflows/ci.yml/badge.svg)

> 100% synthetic demo data. Independent portfolio project.

## The flow

```
ingest --> extract --> validate --(clean)--> post_erp --> posted
                                    |
                                    +--(issues)--> route_review --> apply_reviews --> revalidate --(clean)--> post_erp
                                                                                                    |
                                                                                                    +--(still issues)--> held
```

1. **Ingest** — a document arrives (invoice, PO, contract, receipt).
2. **Extract** — deterministic rules pull typed fields with a confidence score per field.
3. **Validate** — required presence, formats (dates, currency codes, document numbers), and cross-field money consistency (line items ≈ subtotal; subtotal + tax ≈ total, within 1%).
4. **Review** — fields below the confidence threshold (0.8) or with validation issues go to a human queue; corrections are recorded and feed per-field correction stats.
5. **Post** — refused while any validation *error* remains; on success returns a deterministic ERP record (`ERP-<doc-id>`).
6. **Ledger** — every stage is recorded in a hash-chained ledger (`DocumentLedger.verify_chain()`), so the full lineage from source text to ERP posting is tamper-evident.

## Document types and fields

| Type | Key fields |
|---|---|
| Invoice | invoice_no, vendor, date, due_date, currency, line_items, subtotal, tax, total |
| Purchase order | po_number, supplier, order_date, delivery_date, currency, line_items, subtotal, tax, total |
| Contract | agreement_no, parties, effective_date, term_months, value, currency, key_clauses |
| Expense receipt | receipt_no, merchant, date, category, amount, currency |

## Production path

`Extractor` is deterministic heuristics — fast, offline, testable. `LLMExtractor` shares the interface and documents the production upgrade: Azure Document Intelligence (layout + prebuilt invoice/receipt models) with GPT-4o vision as the fallback for unstructured documents. It refuses to run without credentials, so the demo never silently pretends to call a model. Confidence scores and the review queue work identically under either extractor.

## Repo structure

```
docintel/
  documents.py    Document model + synthetic sample factory
  schemas.py      Per-type field schemas (required, types, hints)
  extraction.py   Rule-based Extractor + LLMExtractor stub
  validation.py   Presence, format, and cross-field money checks
  review.py       Human review queue + correction feedback stats
  posting.py      Guarded ERP posting (refused on unresolved errors)
  lineage.py      Hash-chained DocumentLedger
  pipeline.py     Graph runtime + run_document_pipeline()
docs/
  extraction-guide.md   Confidence scoring and the review loop
tests/
  test_docintel.py      36 deterministic tests
```

## Quickstart

```python
from docintel import Extractor, run_document_pipeline, sample_documents

doc = sample_documents()[0]          # synthetic invoice
fields = Extractor().extract(doc)    # typed fields + confidence
print(fields["total"].value)         # 11566.8

state = run_document_pipeline(doc)   # full paper-to-payment flow
print(state["outcome"])              # "posted"
print(state["erp_record"]["erp_ref"])  # "ERP-INV-2041"
```

Run the tests:

```bash
python -m pytest -q
```

## Related work

Pairs with agentic ERP flows (procurement, invoice 3-way match) — document intelligence is the intake layer that feeds them structured, validated data.
