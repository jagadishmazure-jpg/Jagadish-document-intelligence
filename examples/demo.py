"""Paper to payment on synthetic documents: clean, low-confidence and inconsistent cases (offline)."""
from docintel import Extractor, run_document_pipeline, sample_documents
from docintel.documents import sample_invoice

print("Four synthetic document types, straight through:")
for doc in sample_documents():
    s = run_document_pipeline(doc)
    erp = s.get("erp_record") or {}
    print(f"  {doc.id:12} {doc.doc_type.value:16} outcome={s['outcome']:6} erp={erp.get('erp_ref', '-')}")

fuzzy = sample_invoice(fuzzy_vendor=True)
fields = Extractor().extract(fuzzy)
print(f"\nFuzzy vendor line: vendor={fields['vendor'].value!r} confidence={fields['vendor'].confidence:.2f}")
held = run_document_pipeline(fuzzy)
print(f"  without a reviewer correction -> {held['outcome']}")
fixed = run_document_pipeline(fuzzy, corrections={"vendor": "Acme Ingredients Co."}, reviewer="ap-clerk-2")
print(f"  with reviewer correction      -> {fixed['outcome']} ({(fixed.get('erp_record') or {}).get('erp_ref', '-')})")

bad = run_document_pipeline(sample_invoice(mismatch=True))
print(f"\nCorrupted total -> {bad['outcome']}")
for issue in bad["issues"]:
    print(f"  {issue.severity}: {issue.field}: {issue.message}")
print(f"Ledger stages: {bad['ledger'].stages_for('INV-2041')}  verifies={bad['ledger'].verify_chain()}")
