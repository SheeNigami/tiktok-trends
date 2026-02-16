"""TikTok scanner via Playwright (minimal, resilient-ish).

Goal: match the video’s idea (keyword rotation + scan a handful of videos per cycle)
without baking in fragile, account-specific hacks.

How it works:
- Uses a persistent Chromium profile under `./data/playwright/tiktok_profile/`
  so you can log in once (manually) and subsequent runs reuse cookies.
- Rotates a keyword each run via `keywords.next_keyword()`.
- Navigates to TikTok search results for that keyword.
- Scrolls a bit and extracts unique `/video/` links + nearby text.
- Attempts to parse lightweight metrics when present (best-effort).

Important:
TikTok changes DOM frequently and has anti-bot measures. This implementation is
intentionally conservative: it prioritizes *URLs + text* and treats metrics as
optional.

Env vars:
- TIKTOK_HEADLESS=1|0 (default 0)
- TIKTOK_SCAN_VIDEOS=10 (default 10)
- TIKTOK_SCROLLS=6 (default 6)
- TIKTOK_LOCALE=en
- TIKTOK_COLLECTOR=playwright  (enables this collector via registry)

Setup:
- `pip install playwright`
- `playwright install chromium`

Then run:
- `moondev-clawdbot ingest --sources tiktok`
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import Source
from ..keywords import next_keyword
from ..models import Item, stable_id


_VIDEO_RE = re.compile(r"/video/\d+")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")


def _clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s


def _parse_count(s: str) -> Optional[int]:
    """Parse TikTok-ish counts like '12K', '1.3M'."""
    if not s:
        return None
    s = s.strip().upper().replace(",", "")
    m = re.match(r"^([0-9]*\.?[0-9]+)([KMB])?$", s)
    if not m:
        return None
    val = float(m.group(1))
    suf = m.group(2)
    mult = {None: 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suf, 1)
    return int(val * mult)


class TikTokPlaywrightSource(Source):
    name = "tiktok"

    def fetch(self) -> list[Item]:
        # Lazy import so non-Playwright installs still work.
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            ) from e

        headless = _env_bool("TIKTOK_HEADLESS", False)
        max_videos = _env_int("TIKTOK_SCAN_VIDEOS", 10)
        scrolls = _env_int("TIKTOK_SCROLLS", 6)
        locale = os.getenv("TIKTOK_LOCALE", "en")

        kw = next_keyword() or "trending"
        now = datetime.now(timezone.utc).isoformat()

        # Persistent profile to allow manual login.
        user_data_dir = os.path.abspath("./data/playwright/tiktok_profile")
        os.makedirs(user_data_dir, exist_ok=True)

        search_url = f"https://www.tiktok.com/search?q={kw.replace(' ', '%20')}&lang={locale}"

        out: list[Item] = []

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                viewport={"width": 1280, "height": 800},
                locale=locale,
            )
            page = browser.new_page()

            # Try not to look like a bot too aggressively.
            page.set_default_timeout(30_000)
            page.goto(search_url, wait_until="domcontentloaded")

            # If we get a login wall, allow user to log in.
            # Heuristic: presence of "Log in" button/text.
            try:
                if page.get_by_text("Log in").first.is_visible():
                    # Give a clear instruction in console.
                    print("[tiktok] Login appears required. Please log in in the opened browser window, then re-run.")
            except Exception:
                pass

            # Scroll to load results
            for _ in range(scrolls):
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(800)

            # Extract candidate anchors
            anchors = page.eval_on_selector_all(
                "a[href*='/video/']",
                """els => els.map(a => ({href: a.href, text: (a.innerText||'').slice(0,300)}))""",
            )

            seen = set()
            candidates: List[Tuple[str, str]] = []
            for a in anchors or []:
                href = (a.get("href") or "").strip()
                if not href or "/video/" not in href:
                    continue
                # canonicalize (strip query)
                href = href.split("?")[0]
                if href in seen:
                    continue
                seen.add(href)
                candidates.append((href, _clean_text(a.get("text") or "")))
                if len(candidates) >= max_videos:
                    break

            # Best-effort: for each candidate, open and read stats if available.
            for url, anchor_text in candidates:
                metrics: Dict[str, Any] = {"keyword": kw, "collector": "playwright"}
                title = "(tiktok)"
                text = anchor_text or None

                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(1200)

                    # Caption text
                    cap = None
                    for sel in ["[data-e2e='browse-video-desc']", "[data-e2e='video-desc']", "h1", "[class*='Desc']"]:
                        try:
                            cap = page.locator(sel).first.inner_text(timeout=1500)
                            if cap and cap.strip():
                                break
                        except Exception:
                            cap = None
                    if cap:
                        text = _clean_text(cap)
                        title = (text[:80] + "…") if len(text) > 80 else text

                    # Metrics: look for numeric counters (best-effort)
                    # Common pattern: buttons with aria-label like "1234 likes"
                    try:
                        labels = page.eval_on_selector_all(
                            "[aria-label]",
                            """els => els.map(e => e.getAttribute('aria-label')).filter(Boolean).slice(0,200)""",
                        )
                        for lab in labels or []:
                            l = str(lab).lower()
                            m = re.search(r"([0-9][0-9\.,]*\s*[kmb]?)\s+likes", l)
                            if m:
                                metrics["likes"] = _parse_count(m.group(1).replace(" ", ""))
                            m = re.search(r"([0-9][0-9\.,]*\s*[kmb]?)\s+comments", l)
                            if m:
                                metrics["comments"] = _parse_count(m.group(1).replace(" ", ""))
                            m = re.search(r"([0-9][0-9\.,]*\s*[kmb]?)\s+shares", l)
                            if m:
                                metrics["shares"] = _parse_count(m.group(1).replace(" ", ""))
                            m = re.search(r"([0-9][0-9\.,]*\s*[kmb]?)\s+views", l)
                            if m:
                                metrics["views"] = _parse_count(m.group(1).replace(" ", ""))
                    except Exception:
                        pass

                except Exception:
                    # If navigation fails, keep the minimal data.
                    pass

                out.append(
                    Item(
                        item_id=stable_id(self.name, url, title),
                        source=self.name,
                        url=url,
                        title=title,
                        text=text,
                        metrics=metrics,
                        created_at=None,
                        fetched_at=now,
                        raw={"url": url, "anchor_text": anchor_text, "search_url": search_url},
                    )
                )

            try:
                browser.close()
            except Exception:
                pass

        return out
