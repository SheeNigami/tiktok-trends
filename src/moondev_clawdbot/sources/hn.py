from __future__ import annotations

import requests
from datetime import datetime, timezone

from .base import Source
from ..models import Item, stable_id


HN_BASE = "https://hacker-news.firebaseio.com/v0"


def _iso_from_unix(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class HackerNewsSource(Source):
    name = "hn"

    def __init__(self, limit: int = 50, kind: str = "top"):
        self.limit = limit
        self.kind = kind

    def fetch(self) -> list[Item]:
        ids = requests.get(f"{HN_BASE}/{self.kind}stories.json", timeout=30).json()
        ids = (ids or [])[: self.limit]
        items: list[Item] = []
        for i in ids:
            j = requests.get(f"{HN_BASE}/item/{i}.json", timeout=30).json() or {}
            if j.get("type") not in ("story",):
                continue
            url = j.get("url") or f"https://news.ycombinator.com/item?id={j.get('id')}"
            title = j.get("title") or "(no title)"
            text = j.get("text")
            metrics = {
                "points": j.get("score") or 0,
                "comments": j.get("descendants") or 0,
                "by": j.get("by"),
            }
            it = Item(
                item_id=stable_id(self.name, str(j.get("id")), url),
                source=self.name,
                url=url,
                title=title,
                text=text,
                metrics=metrics,
                created_at=_iso_from_unix(j.get("time")),
                fetched_at=datetime.now(timezone.utc).isoformat(),
                raw=j,
            )
            items.append(it)
        return items
