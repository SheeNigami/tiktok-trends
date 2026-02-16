from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

from .base import Source
from ..models import Item, stable_id


class XMockSource(Source):
    """Placeholder for the video’s X/Twitter ingestion step.

    - If `./config/x_seed.jsonl` exists, reads it as JSON Lines with {url,title,text,metrics}.
    - Otherwise generates a couple of mock 'viral tweet' items.

    Real X ingestion requires credentials and is intentionally not baked in.
    """

    name = "x_mock"

    def __init__(self, seed_file: str = "./config/x_seed.jsonl"):
        self.seed_file = seed_file

    def fetch(self) -> list[Item]:
        now = datetime.now(timezone.utc).isoformat()
        p = Path(self.seed_file)
        items: list[Item] = []
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                j = json.loads(ln)
                url = j.get("url") or "https://x.com/"
                title = j.get("title") or "(tweet)"
                text = j.get("text")
                metrics = j.get("metrics") or {}
                items.append(
                    Item(
                        item_id=stable_id(self.name, url, title),
                        source=self.name,
                        url=url,
                        title=title,
                        text=text,
                        metrics=metrics,
                        created_at=j.get("created_at"),
                        fetched_at=now,
                        raw=j,
                    )
                )
            return items

        # fallback mock
        mock = [
            {
                "url": "https://x.com/example/status/1",
                "title": "New AI tool hits 10k users in 48h",
                "text": "If you do X, you can get Y in Z hours…",
                "metrics": {"likes": 12000, "retweets": 1800, "replies": 220},
            },
            {
                "url": "https://x.com/example/status/2",
                "title": "Open-source agent framework drops",
                "text": "Repo + quickstart + benchmarks…",
                "metrics": {"likes": 6000, "retweets": 900, "replies": 150},
            },
        ]
        for j in mock:
            items.append(
                Item(
                    item_id=stable_id(self.name, j["url"], j["title"]),
                    source=self.name,
                    url=j["url"],
                    title=j["title"],
                    text=j.get("text"),
                    metrics=j.get("metrics") or {},
                    created_at=None,
                    fetched_at=now,
                    raw=j,
                )
            )
        return items
