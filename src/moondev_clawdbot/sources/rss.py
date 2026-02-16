from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import feedparser

from .base import Source
from ..models import Item, stable_id


def _best_date(entry) -> str | None:
    for k in ("published_parsed", "updated_parsed"):
        v = getattr(entry, k, None)
        if v:
            return datetime(*v[:6], tzinfo=timezone.utc).isoformat()
    return None


class RssSource(Source):
    name = "rss"

    def __init__(self, feeds_file: str = "./config/rss_feeds.txt", limit_per_feed: int = 20):
        self.feeds_file = feeds_file
        self.limit_per_feed = limit_per_feed

    def fetch(self) -> list[Item]:
        p = Path(self.feeds_file)
        if not p.exists():
            return []
        feeds = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
        out: list[Item] = []
        for url in feeds:
            d = feedparser.parse(url)
            for e in (d.entries or [])[: self.limit_per_feed]:
                link = getattr(e, "link", None) or url
                title = getattr(e, "title", None) or "(no title)"
                summary = getattr(e, "summary", None)
                it = Item(
                    item_id=stable_id(self.name, link, title),
                    source=self.name,
                    url=link,
                    title=title,
                    text=summary,
                    metrics={"feed": url},
                    created_at=_best_date(e),
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    raw={"feed": url, "entry": {k: getattr(e, k) for k in dir(e) if not k.startswith('_') and k in ("title","link","summary")}},
                )
                out.append(it)
        return out
