"""docintel: enterprise intelligent document processing.

Extract structured data from business documents, validate it, route
low-confidence fields to human review, and post clean records to ERP —
the "paper to payment" flow.

Pipeline::

    ingest --> extract --> validate --(clean)--> post_erp --> posted
                                  |
                                  +--(issues)--> human_review --> revalidate --(clean)--> post_erp
                                                                              |
                                                                              +--(still issues)--> held

All demo data is synthetic. Extraction is deterministic heuristics;
``LLMExtractor`` documents the production path (Azure Document
Intelligence / GPT-4o vision) without requiring any API key.
"""

from docintel.documents import Document, DocumentType, sample_documents
from docintel.extraction import ExtractedField, Extractor, LLMExtractor
from docintel.lineage import DocumentLedger
from docintel.pipeline import run_document_pipeline
from docintel.posting import ERPRecord, PostingRefused, post_to_erp
from docintel.review import ReviewQueue
from docintel.schemas import FIELD_SCHEMAS
from docintel.validation import ValidationIssue, validate_extraction

__all__ = [
    "Document",
    "DocumentType",
    "DocumentLedger",
    "ERPRecord",
    "ExtractedField",
    "Extractor",
    "FIELD_SCHEMAS",
    "LLMExtractor",
    "PostingRefused",
    "ReviewQueue",
    "ValidationIssue",
    "post_to_erp",
    "run_document_pipeline",
    "sample_documents",
    "validate_extraction",
]
