from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any
import hashlib
import json


def stable_id(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return h[:24]


@dataclass
class Item:
    # Core normalized schema
    item_id: str
    source: str
    url: str
    title: str
    text: str | None

    # Metrics are source-specific (points, comments, upvotes, etc.)
    metrics: dict[str, Any]

    # Derived
    score: float | None = None
    score_breakdown: dict[str, Any] | None = None

    # Timestamps as ISO strings for portability
    created_at: str | None = None
    fetched_at: str | None = None

    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def metrics_json(self) -> str:
        return json.dumps(self.metrics or {}, ensure_ascii=False)

    def raw_json(self) -> str:
        return json.dumps(self.raw or {}, ensure_ascii=False)
