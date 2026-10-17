"""Human review queue: the correction feedback loop.

Fields land in the queue when their extraction confidence is below the
threshold or when validation raised an issue against them. A reviewer
submits corrected values; ``review_stats()`` reports the per-field
correction rate, which tells the team which extraction rules to improve
next — the loop that makes the system better over time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from docintel.extraction import ExtractedField
from docintel.validation import ValidationIssue

#: Fields below this confidence are routed to human review.
DEFAULT_CONFIDENCE_THRESHOLD = 0.8


@dataclass
class ReviewItem:
    field_name: str
    extracted_value: Any
    confidence: float
    reason: str
    status: str = "pending"  # pending | corrected
    corrected_value: Any = None
    reviewer: Optional[str] = None


@dataclass
class CorrectionRecord:
    field_name: str
    old_value: Any
    new_value: Any
    reviewer: str


class ReviewQueue:
    """Collect fields needing review; record corrections; report stats."""

    def __init__(self, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> None:
        self.threshold = confidence_threshold
        self._items: Dict[str, ReviewItem] = {}
        self._corrections: List[CorrectionRecord] = []
        self._routed_count: Dict[str, int] = {}

    def route(
        self,
        fields: Dict[str, ExtractedField],
        issues: List[ValidationIssue],
    ) -> List[ReviewItem]:
        """Queue low-confidence fields and fields with validation issues."""
        flagged = {i.field for i in issues}
        for name, found in fields.items():
            reasons: List[str] = []
            if found.confidence < self.threshold:
                reasons.append(f"low confidence {found.confidence:.2f} < {self.threshold}")
            if name in flagged:
                reasons.append("validation issue")
            if reasons:
                self._items[name] = ReviewItem(
                    field_name=name,
                    extracted_value=found.value,
                    confidence=found.confidence,
                    reason="; ".join(reasons),
                )
                self._routed_count[name] = self._routed_count.get(name, 0) + 1
        # Fields missing entirely are also reviewable.
        for issue in issues:
            if issue.field not in fields and issue.field not in self._items:
                self._items[issue.field] = ReviewItem(
                    field_name=issue.field,
                    extracted_value=None,
                    confidence=0.0,
                    reason=f"missing: {issue.message}",
                )
                self._routed_count[issue.field] = self._routed_count.get(issue.field, 0) + 1
        return self.pending()

    def pending(self) -> List[ReviewItem]:
        return [i for i in self._items.values() if i.status == "pending"]

    def submit_review(
        self, field_name: str, corrected_value: Any, reviewer: str
    ) -> ReviewItem:
        """Record a human correction for a queued field."""
        item = self._items.get(field_name)
        if item is None:
            raise KeyError(f"field {field_name!r} is not in the review queue")
        if item.status == "corrected":
            raise ValueError(f"field {field_name!r} was already corrected")
        item.status = "corrected"
        item.corrected_value = corrected_value
        item.reviewer = reviewer
        self._corrections.append(
            CorrectionRecord(field_name, item.extracted_value, corrected_value, reviewer)
        )
        return item

    def corrected_fields(self) -> Dict[str, Any]:
        """Corrected values keyed by field name."""
        return {
            name: item.corrected_value
            for name, item in self._items.items()
            if item.status == "corrected"
        }

    def is_clear(self) -> bool:
        """True when nothing is still pending review."""
        return not self.pending()

    def review_stats(self) -> Dict[str, Dict[str, float]]:
        """Per-field stats: routed count, correction count, correction rate."""
        stats: Dict[str, Dict[str, float]] = {}
        corrected: Dict[str, int] = {}
        for c in self._corrections:
            corrected[c.field_name] = corrected.get(c.field_name, 0) + 1
        for name, routed in self._routed_count.items():
            n_corrected = corrected.get(name, 0)
            stats[name] = {
                "routed": float(routed),
                "corrected": float(n_corrected),
                "correction_rate": round(n_corrected / routed, 3) if routed else 0.0,
            }
        return stats

    # Backwards-compatible alias used by older callers.
    queued = pending
