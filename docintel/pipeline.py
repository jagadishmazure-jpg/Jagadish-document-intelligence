"""Graph-based document processing pipeline: paper to payment.

Business scenario: a vendor invoice arrives as text. The pipeline
ingests it, extracts structured fields with confidence scores,
validates them, and routes clean documents straight to ERP posting.
Documents with low-confidence fields or validation errors go to a human
review queue; corrected values are re-validated, and only then posted.
Documents that still carry errors after review are held.

Topology::

    ingest --> extract --> validate --(clean)--> post_erp --> posted
                                    |
                                    +--(issues)--> route_review --> apply_reviews --> revalidate --(clean)--> post_erp
                                                                                                  |
                                                                                                  +--(still issues)--> held

``corrections`` maps field names to reviewer-supplied values and is
applied at the ``apply_reviews`` node (pass reviewer corrections to
exercise the review path; omit them to exercise the held path). All
paths terminate. Every stage is recorded in the hash-chained ledger.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from docintel.documents import Document
from docintel.extraction import ExtractedField, Extractor
from docintel.lineage import DocumentLedger
from docintel.posting import PostingRefused, post_to_erp
from docintel.review import ReviewQueue
from docintel.validation import validate_extraction

NodeFn = Callable[[Dict[str, Any]], Dict[str, Any]]
Predicate = Callable[[Dict[str, Any]], bool]


class Graph:
    """Minimal deterministic graph runtime (stdlib only).

    Node/edge semantics mirror a standard workflow builder: ``add_node``
    registers ``fn(state) -> dict``; ``add_edge`` chains sequentially;
    ``add_conditional`` routes on a predicate. The first-added node is the
    start node; nodes with no outgoing edge are terminal. A ``max_steps``
    guard keeps cycles safe.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, NodeFn] = {}
        self._edges: Dict[str, str] = {}
        self._conditionals: Dict[str, Tuple[Predicate, str, str]] = {}

    def add_node(self, name: str, fn: NodeFn) -> "Graph":
        if name in self._nodes:
            raise ValueError(f"duplicate node name: {name!r}")
        self._nodes[name] = fn
        return self

    def add_edge(self, frm: str, to: str) -> "Graph":
        if frm in self._conditionals:
            raise ValueError(f"node {frm!r} already has a conditional edge")
        self._edges[frm] = to
        return self

    def add_conditional(
        self, frm: str, predicate: Predicate, to_true: str, to_false: str
    ) -> "Graph":
        if frm in self._edges:
            raise ValueError(f"node {frm!r} already has an unconditional edge")
        self._conditionals[frm] = (predicate, to_true, to_false)
        return self

    def run(self, initial_state: Dict[str, Any], max_steps: int = 50) -> Dict[str, Any]:
        if not self._nodes:
            raise ValueError("cannot run an empty graph")
        state = dict(initial_state)
        current: Optional[str] = next(iter(self._nodes))
        steps = 0
        while current is not None:
            if steps >= max_steps:
                raise RuntimeError("max_steps exceeded")
            result = self._nodes[current](state)
            if not isinstance(result, dict):
                raise TypeError(f"node {current!r} did not return a dict")
            state.update(result)
            steps += 1
            if current in self._conditionals:
                predicate, to_true, to_false = self._conditionals[current]
                current = to_true if predicate(state) else to_false
            else:
                current = self._edges.get(current)
        return state


def _summarize_fields(fields: Dict[str, ExtractedField]) -> Dict[str, Any]:
    return {
        name: {"value": f.value, "confidence": f.confidence}
        for name, f in fields.items()
    }


def run_document_pipeline(
    document: Document,
    corrections: Optional[Dict[str, Any]] = None,
    reviewer: str = "demo-reviewer",
    confidence_threshold: float = 0.8,
) -> Dict[str, Any]:
    """Run the paper-to-payment pipeline end to end, offline and deterministic.

    Returns the final state: ``outcome`` (``"posted"`` or ``"held"``),
    per-node results (``extraction``, ``validation``, ``review``,
    ``erp_record``), and the ``ledger`` with every stage recorded.
    """
    extractor = Extractor()
    queue = ReviewQueue(confidence_threshold=confidence_threshold)
    ledger = DocumentLedger()
    supplied = dict(corrections or {})

    def ingest(state: Dict[str, Any]) -> Dict[str, Any]:
        ledger.record("ingested", document.id, {"source": document.source_name})
        return {"document_id": document.id, "doc_type": document.doc_type.value}

    def extract(state: Dict[str, Any]) -> Dict[str, Any]:
        fields = extractor.extract(document)
        ledger.record(
            "extracted",
            document.id,
            {"fields": sorted(fields), "min_confidence": min((f.confidence for f in fields.values()), default=0.0)},
        )
        return {"fields": fields, "extraction": _summarize_fields(fields)}

    def validate(state: Dict[str, Any]) -> Dict[str, Any]:
        issues = validate_extraction(document.doc_type, state["fields"])
        # Review triggers on validation errors OR low-confidence fields.
        needs_review = any(i.severity == "error" for i in issues) or any(
            f.confidence < confidence_threshold for f in state["fields"].values()
        )
        ledger.record(
            "validated",
            document.id,
            {
                "errors": sum(1 for i in issues if i.severity == "error"),
                "warnings": sum(1 for i in issues if i.severity == "warning"),
                "needs_review": needs_review,
            },
        )
        return {
            "issues": issues,
            "validation": [
                {"field": i.field, "severity": i.severity, "message": i.message}
                for i in issues
            ],
            "has_errors": any(i.severity == "error" for i in issues),
            "needs_review": needs_review,
        }

    def route_review(state: Dict[str, Any]) -> Dict[str, Any]:
        items = queue.route(state["fields"], state["issues"])
        ledger.record(
            "review_routed", document.id, {"queued": [i.field_name for i in items]}
        )
        return {"review_items": [i.field_name for i in items]}

    def apply_reviews(state: Dict[str, Any]) -> Dict[str, Any]:
        applied: List[str] = []
        for name, value in supplied.items():
            if name in queue._items:
                queue.submit_review(name, value, reviewer)
                applied.append(name)
        # Merge corrections back into the working field set at full confidence.
        fields: Dict[str, ExtractedField] = dict(state["fields"])
        for name, value in queue.corrected_fields().items():
            fields[name] = ExtractedField(name, value, 1.0, "human-review")
        ledger.record("reviewed", document.id, {"corrected": applied})
        return {"fields": fields, "applied_corrections": applied}

    def revalidate(state: Dict[str, Any]) -> Dict[str, Any]:
        issues = validate_extraction(document.doc_type, state["fields"])
        needs_review = any(i.severity == "error" for i in issues) or any(
            f.confidence < confidence_threshold for f in state["fields"].values()
        )
        ledger.record(
            "revalidated",
            document.id,
            {"errors": sum(1 for i in issues if i.severity == "error")},
        )
        return {
            "issues": issues,
            "has_errors": any(i.severity == "error" for i in issues),
            "needs_review": needs_review,
        }

    def post_erp(state: Dict[str, Any]) -> Dict[str, Any]:
        try:
            record = post_to_erp(document.id, document.doc_type, state["fields"], state["issues"])
        except PostingRefused as exc:
            return {"outcome": "held", "hold_reason": str(exc)}
        ledger.record("posted", document.id, {"erp_ref": record.erp_ref})
        return {
            "erp_record": {
                "doc_id": record.doc_id,
                "erp_ref": record.erp_ref,
                "status": record.status,
                "total_posted": record.total_posted,
            },
            "outcome": "posted",
        }

    def held(state: Dict[str, Any]) -> Dict[str, Any]:
        ledger.record(
            "held",
            document.id,
            {"reason": "unresolved validation errors after review"},
        )
        return {
            "outcome": "held",
            "hold_reason": "unresolved validation errors after human review",
        }

    def _clean(state: Dict[str, Any]) -> bool:
        return not state.get("needs_review", True)

    graph = Graph()
    graph.add_node("ingest", ingest)
    graph.add_node("extract", extract)
    graph.add_node("validate", validate)
    graph.add_node("route_review", route_review)
    graph.add_node("apply_reviews", apply_reviews)
    graph.add_node("revalidate", revalidate)
    graph.add_node("post_erp", post_erp)
    graph.add_node("held", held)
    graph.add_edge("ingest", "extract")
    graph.add_edge("extract", "validate")
    graph.add_edge("route_review", "apply_reviews")
    graph.add_edge("apply_reviews", "revalidate")
    graph.add_conditional("validate", _clean, "post_erp", "route_review")
    graph.add_conditional("revalidate", _clean, "post_erp", "held")
    # "post_erp" and "held" have no outgoing edge: terminal nodes.

    final = graph.run({"document": document})
    final["ledger"] = ledger
    return final
