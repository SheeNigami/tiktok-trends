from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .models import Item


DEFAULT_KEYWORDS = [
    "ai",
    "agent",
    "open source",
    "launch",
    "product hunt",
    "saas",
    "startup",
    "viral",
    "growth",
    "automation",
]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _safe_log1p(x: Any) -> float:
    try:
        return math.log1p(max(0.0, float(x)))
    except Exception:
        return 0.0


def _recency_boost(created_at_iso: str | None, half_life_hours: float = 24.0) -> float:
    if not created_at_iso:
        return 0.0
    try:
        dt = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
        # exponential decay from 1 -> 0
        return math.exp(-math.log(2) * (age_h / half_life_hours))
    except Exception:
        return 0.0


def _keyword_score(title: str, text: str | None, keywords: list[str]) -> float:
    blob = (title + "\n" + (text or "")).lower()
    hits = 0
    for kw in keywords:
        if kw.lower() in blob:
            hits += 1
    if not keywords:
        return 0.0
    return hits / max(1, len(keywords))


def score_item(it: Item, keywords: list[str] | None = None) -> Item:
    kw = keywords or DEFAULT_KEYWORDS

    # Engagement proxy
    m = it.metrics or {}
    points = m.get("points") or m.get("likes") or m.get("upvotes") or 0
    comments = m.get("comments") or m.get("replies") or 0
    shares = m.get("retweets") or m.get("shares") or 0
    views = m.get("views") or 0
    view_velocity = m.get("view_velocity")  # can be 0..1 or views/sec depending on your seed

    eng = (
        0.45 * _safe_log1p(points)
        + 0.25 * _safe_log1p(comments)
        + 0.15 * _safe_log1p(shares)
        + 0.15 * _safe_log1p(views)
    )

    vel_n = 0.0
    if view_velocity is not None:
        try:
            vv = float(view_velocity)
            # If vv is already 0..1, keep it; otherwise log-normalize
            vel_n = vv if 0.0 <= vv <= 1.0 else _sigmoid((_safe_log1p(vv) - 2.0) / 1.2)
        except Exception:
            vel_n = 0.0

    # Normalize engagement with sigmoid
    eng_n = _sigmoid((eng - 2.0) / 1.5)

    rec = _recency_boost(it.created_at, half_life_hours=18.0)
    kw_n = _keyword_score(it.title, it.text, kw)

    inv_n = 0.0
    inv = m.get("investable")
    if isinstance(inv, list) and inv:
        # boost when there's a clear investable path
        statuses = [(x or {}).get("status", "").lower() for x in inv if isinstance(x, dict)]
        inv_n = 1.0 if any(s == "public" for s in statuses) else 0.6

    # Weighted sum (simple + interpretable)
    # The video emphasizes **view velocity** + an "investable check" (ticker/parent/pre-IPO).
    score = 0.50 * eng_n + 0.19 * rec + 0.13 * kw_n + 0.15 * vel_n + 0.03 * inv_n

    it.score = float(max(0.0, min(1.0, score)))
    it.score_breakdown = {
        "engagement_raw": eng,
        "engagement_norm": eng_n,
        "view_velocity_norm": vel_n,
        "recency": rec,
        "keyword": kw_n,
        "investable": inv_n,
        "weights": {
            "engagement": 0.50,
            "recency": 0.19,
            "keyword": 0.13,
            "view_velocity": 0.15,
            "investable": 0.03,
        },
    }
    return it


def score_items(items: list[Item], keywords: list[str] | None = None) -> list[Item]:
    return [score_item(it, keywords=keywords) for it in items]
