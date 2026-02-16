from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import feedparser

from .base import Source
from ..models import Item, stable_id


class RedditRssSource(Source):
    name = "reddit"

    def __init__(self, subreddits_file: str = "./config/reddit_subreddits.txt", limit_per_sub: int = 15):
        self.subreddits_file = subreddits_file
        self.limit_per_sub = limit_per_sub

    def fetch(self) -> list[Item]:
        p = Path(self.subreddits_file)
        if not p.exists():
            return []

        subs = [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]
        out: list[Item] = []
        for sub in subs:
            url = f"https://www.reddit.com/r/{sub}/hot/.rss"
            d = feedparser.parse(url, request_headers={"User-Agent": "moondev-clawdbot/0.1"})
            for e in (d.entries or [])[: self.limit_per_sub]:
                link = getattr(e, "link", None) or url
                title = getattr(e, "title", None) or "(no title)"
                summary = getattr(e, "summary", None)
                created_at = None
                if getattr(e, "published_parsed", None):
                    pp = e.published_parsed
                    created_at = datetime(*pp[:6], tzinfo=timezone.utc).isoformat()

                it = Item(
                    item_id=stable_id(self.name, link, title),
                    source=self.name,
                    url=link,
                    title=title,
                    text=summary,
                    metrics={"subreddit": sub},
                    created_at=created_at,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    raw={"subreddit": sub, "entry": {"title": title, "link": link}},
                )
                out.append(it)
        return out
