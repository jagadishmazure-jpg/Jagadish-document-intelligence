# Extraction guide: confidence scoring and the review loop

## Confidence scoring

Every extracted field carries a confidence score in `[0, 1]`:

| Score | Meaning | Example |
|---|---|---|
| 1.0 | Exact labeled hit | `Invoice No: INV-2041` |
| 0.7 | Fuzzy fallback — the bare pattern with no label | `INV-2041` appearing unlabeled |
| 0.6 | Heuristic reconstruction | vendor name recovered from a `(vendor)` mention |
| 0.5 | Partial hit | a line-item row that does not fully parse |
| 0.0 | Missing | field not found at all |

Rules are ordered: the extractor tries exact patterns first and only
falls back when they miss, so scores degrade gracefully instead of
failing silently.

## When fields go to human review

A field is routed to the review queue when **either** condition holds:

- its confidence is below the threshold (default `0.8`), or
- validation raised an issue against it (missing, bad format, or a
  cross-field inconsistency such as a totals mismatch).

The queue records *why* each field was routed (`"low confidence 0.60 <
0.80"`, `"validation issue"`, `"missing: ..."`), so reviewers see the
reason alongside the extracted value and source snippet.

## The correction feedback loop

`submit_review(field_name, corrected_value, reviewer)` records each
correction. `review_stats()` aggregates per-field:

```python
{"vendor": {"routed": 12.0, "corrected": 9.0, "correction_rate": 0.75}}
```

A high correction rate on a field means the extraction rules for that
field are weak — that is the prioritized backlog for improving rules
(or for fine-tuning the model-backed extractor in production).

## Warnings vs errors

Validation issues have severities. **Errors** block ERP posting
(missing required field, bad date, totals mismatch). **Warnings** are
informational (a field outside the schema) and never block. The
pipeline re-validates after review: only documents that are error-free
after corrections reach `post_erp`; the rest terminate as `held` with a
recorded reason.
