from __future__ import annotations

import os

from .base import Source
from .hn import HackerNewsSource
from .rss import RssSource
from .reddit import RedditRssSource
from .x_mock import XMockSource
from .tiktok_mock import TikTokMockSource
from .tiktok_playwright_stub import TikTokPlaywrightSource


def make_sources(names: list[str]) -> list[Source]:
    out: list[Source] = []
    for n in names:
        n = n.strip()
        if not n:
            continue
        if n in ("tiktok", "tt"):
            # Default remains mock/seed-based unless explicitly enabled.
            if (os.getenv("TIKTOK_COLLECTOR") or "").lower() in ("playwright", "pw", "browser"):
                out.append(TikTokPlaywrightSource())
            else:
                out.append(TikTokMockSource())
        elif n == "hn":
            out.append(HackerNewsSource())
        elif n == "rss":
            out.append(RssSource())
        elif n == "reddit":
            out.append(RedditRssSource())
        elif n in ("x", "x_mock", "twitter"):
            out.append(XMockSource())
        else:
            raise ValueError(f"Unknown source: {n}")
    return out
