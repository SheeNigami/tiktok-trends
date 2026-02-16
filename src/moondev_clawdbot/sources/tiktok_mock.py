from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

from .base import Source
from ..models import Item, stable_id
from ..keywords import next_keyword


class TikTokMockSource(Source):
    """Placeholder for TikTok 'For You' / keyword scanning.

    The real video uses browser automation + an LLM to scroll TikTok and capture
    view velocity / engagement.

    This implementation reads `./config/tiktok_seed.jsonl` if present.

    Each JSON line can contain:
      {"url":..., "title":..., "text":..., "metrics": {"views":...,"likes":...,"comments":...,"shares":...,"view_velocity":...}, "created_at":...}

    If the file is missing, it returns a small set of mock viral videos.
    """

    name = "tiktok"

    def __init__(self, seed_file: str = "./config/tiktok_seed.jsonl"):
        self.seed_file = seed_file

    def fetch(self) -> list[Item]:
        now = datetime.now(timezone.utc).isoformat()
        current_kw = next_keyword()  # rotates per run (matches the video idea)
        p = Path(self.seed_file)
        out: list[Item] = []
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                j = json.loads(ln)
                url = j.get("url") or "https://www.tiktok.com/"
                title = j.get("title") or "(tiktok)"
                text = j.get("text")
                metrics = j.get("metrics") or {}
                metrics.setdefault("collector", "mock")
                if current_kw and "keyword" not in metrics:
                    metrics["keyword"] = current_kw
                out.append(
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
            return out

        mock = [
            {
                "url": "https://www.tiktok.com/@example/video/111",
                "title": "New drink brand is everywhere (Gen Z)",
                "text": "Seeing this brand in every college video…",
                "metrics": {"views": 2_500_000, "likes": 210_000, "comments": 3_200, "shares": 18_000, "view_velocity": 0.82, "keyword": current_kw, "collector": "mock"},
            },
            {
                "url": "https://www.tiktok.com/@example/video/222",
                "title": "Abercrombie haul revival??",
                "text": "ABERCROMBIE is back and no one told Wall St.",
                "metrics": {"views": 1_200_000, "likes": 95_000, "comments": 1_100, "shares": 7_500, "view_velocity": 0.74, "keyword": current_kw, "collector": "mock"},
            },
        ]
        for j in mock:
            out.append(
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
        return out
