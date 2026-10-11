"""Hash-chained document ledger: source -> extract -> validate -> review -> post.

Every pipeline stage records an entry carrying a SHA-256 hash chained to
the previous entry, so tampering with any earlier stage invalidates
every later hash. ``verify_chain()`` detects tampering or gaps.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List


def _entry_hash(previous_hash: str, body: str) -> str:
    return hashlib.sha256(f"{previous_hash}|{body}".encode("utf-8")).hexdigest()


class DocumentLedger:
    """Append-only, hash-chained ledger of document processing stages."""

    GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._last_hash = self.GENESIS_HASH

    def record(self, stage: str, doc_id: str, details: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Append one stage entry; returns the entry dict."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "doc_id": doc_id,
            "details": details or {},
        }
        body = json.dumps(entry, sort_keys=True, default=str)
        entry["previous_hash"] = self._last_hash
        entry["hash"] = _entry_hash(self._last_hash, body)
        self._last_hash = entry["hash"]
        self._entries.append(entry)
        return entry

    def entries(self) -> List[Dict[str, Any]]:
        return list(self._entries)

    def stages_for(self, doc_id: str) -> List[str]:
        """Stage names recorded for a document, in order."""
        return [e["stage"] for e in self._entries if e["doc_id"] == doc_id]

    def verify_chain(self) -> bool:
        """Verify hash-chain integrity; False on any tampering or gap."""
        previous = self.GENESIS_HASH
        for entry in self._entries:
            body_entry = {
                k: v for k, v in entry.items() if k not in ("hash", "previous_hash")
            }
            body = json.dumps(body_entry, sort_keys=True, default=str)
            if entry.get("previous_hash") != previous:
                return False
            if entry.get("hash") != _entry_hash(previous, body):
                return False
            previous = entry["hash"]
        return True

    def export_jsonl(self) -> str:
        """Serialize the ledger as JSONL (one entry per line)."""
        return "\n".join(json.dumps(e, default=str) for e in self._entries)
