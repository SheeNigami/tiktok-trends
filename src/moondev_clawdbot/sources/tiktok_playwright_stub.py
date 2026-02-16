"""TikTok scanner via Playwright (minimal, resilient-ish).

Goal: match the video’s idea (keyword rotation + scan a handful of videos per cycle)
without baking in fragile, account-specific hacks.

How it works:
- Uses a persistent Chromium profile under `./data/playwright/tiktok_profile/`
  so you can log in once (manually) and subsequent runs reuse cookies.
- Rotates a keyword each run via `keywords.next_keyword()`.
- Navigates to TikTok search results for that keyword.
- Scrolls a bit and extracts unique `/video/` links + nearby text.
- Opens each video page and extracts caption + best-effort metadata.
- Captures per-post screenshots (for later vision/LLM enrichment).

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

Screenshots (always captured for collected TikToks):
- TIKTOK_SCREENSHOT_COUNT=4 (default 4; max 5)
- TIKTOK_SCREENSHOT_INTERVAL_SEC=2 (default 2)

Setup:
- `pip install playwright`
- `playwright install chromium`

Then run:
- `moondev-clawdbot ingest --sources tiktok`
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
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


def _relpath_posix(p: str) -> str:
    rel = os.path.relpath(p, start=os.path.abspath("."))
    return rel.replace(os.sep, "/")


def _hashtags_from_text(text: str | None) -> list[str]:
    if not text:
        return []
    # TikTok tags are often alnum/_; keep it conservative.
    tags = re.findall(r"(?<!\w)#([\w_]{1,64})", text)
    out = [f"#{t}" for t in tags if t]
    # de-dupe while preserving order
    seen = set()
    uniq = []
    for t in out:
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)
    return uniq


def _parse_sound_text(s: str | None) -> tuple[str | None, str | None]:
    """Heuristically split a TikTok sound string into (title, artist)."""
    if not s:
        return None, None
    s = _clean_text(s)
    if not s:
        return None, None

    # common: "original sound - user" or "Song Title - Artist"
    if " - " in s:
        a, b = s.split(" - ", 1)
        return _clean_text(a) or None, _clean_text(b) or None

    # sometimes uses a bullet
    if " • " in s:
        a, b = s.split(" • ", 1)
        return _clean_text(a) or None, _clean_text(b) or None

    return s, None


def _try_extract_next_data(page) -> dict | None:
    """Best-effort: parse TikTok __NEXT_DATA__ to extract stable metadata."""
    try:
        txt = page.locator("script#__NEXT_DATA__").first.inner_text(timeout=1500)
        if not txt or not txt.strip():
            return None
        return json.loads(txt)
    except Exception:
        return None


def _dig(d: Any, path: list[str]) -> Any:
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur.get(k)
    return cur


def _find_first_dict_with_key(obj: Any, key: str, max_nodes: int = 20_000) -> dict | None:
    """Shallow-ish DFS to find first dict containing `key`.

    Hard node limit to avoid pathological page JSON.
    """
    stack = [obj]
    seen = 0
    while stack and seen < max_nodes:
        cur = stack.pop()
        seen += 1
        if isinstance(cur, dict):
            if key in cur and isinstance(cur.get(key), dict):
                return cur
            for v in cur.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for v in cur:
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return None


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

        # Screenshots are ALWAYS captured for collected TikToks.
        # Default: every 2 seconds, up to 4 frames (user preference), but allow overrides.
        screenshot_count = max(1, _env_int("TIKTOK_SCREENSHOT_COUNT", 4))
        screenshot_interval_sec = max(0.25, _env_float("TIKTOK_SCREENSHOT_INTERVAL_SEC", 2.0))
        effective_count = min(screenshot_count, 5)

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
                    print(
                        "[tiktok] Login appears required. Please log in in the opened browser window, then re-run."
                    )
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

            # If search extraction fails (TikTok can error / block automation),
            # fall back to seed URLs if present so the collector still works.
            if not candidates:
                try:
                    seed_path = os.path.abspath("./config/tiktok_seed.jsonl")
                    if os.path.exists(seed_path):
                        for ln in open(seed_path, "r", encoding="utf-8").read().splitlines():
                            if not ln.strip():
                                continue
                            j = json.loads(ln)
                            href = (j.get("url") or "").strip()
                            if not href or "/video/" not in href:
                                continue
                            href = href.split("?")[0]
                            if href in seen:
                                continue
                            seen.add(href)
                            candidates.append((href, _clean_text(j.get("text") or j.get("title") or "")))
                            if len(candidates) >= max_videos:
                                break
                        if candidates:
                            print(f"[tiktok] No links found on search page; falling back to {seed_path} ({len(candidates)} urls)")
                except Exception:
                    pass

            # Best-effort: for each candidate, open and read stats if available.
            for url, anchor_text in candidates:
                metrics: Dict[str, Any] = {"keyword": kw, "collector": "playwright"}
                title = "(tiktok)"
                text = anchor_text or None
                created_at: str | None = None

                try:
                    page.goto(url, wait_until="domcontentloaded")
                    page.wait_for_timeout(1200)

                    # Metadata from __NEXT_DATA__ (best effort, more stable than DOM)
                    nd = _try_extract_next_data(page)
                    item_struct = None
                    if nd:
                        item_struct = _dig(nd, ["props", "pageProps", "itemInfo", "itemStruct"])
                        if not isinstance(item_struct, dict):
                            # fallback: find any dict containing itemStruct
                            w = _find_first_dict_with_key(nd, "itemStruct")
                            if w and isinstance(w.get("itemStruct"), dict):
                                item_struct = w.get("itemStruct")

                    if isinstance(item_struct, dict):
                        # creator
                        try:
                            au = (item_struct.get("author") or {})
                            uid = au.get("uniqueId") or au.get("uniqueID")
                            if uid:
                                metrics["creator"] = str(uid)
                        except Exception:
                            pass

                        # hashtags
                        try:
                            tx = item_struct.get("textExtra")
                            tags = []
                            if isinstance(tx, list):
                                for e in tx:
                                    if not isinstance(e, dict):
                                        continue
                                    hn = e.get("hashtagName")
                                    if hn:
                                        tags.append(f"#{hn}")
                            if tags:
                                metrics["hashtags"] = list(dict.fromkeys(tags))
                        except Exception:
                            pass

                        # sound/music
                        try:
                            mu = (item_struct.get("music") or {})
                            st = mu.get("title")
                            sa = mu.get("authorName") or mu.get("author")
                            if st:
                                metrics["sound_title"] = str(st)
                            if sa:
                                metrics["sound_artist"] = str(sa)
                        except Exception:
                            pass

                        # posted time
                        try:
                            ct = item_struct.get("createTime")
                            if ct is not None:
                                ts = int(ct)
                                created_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                                metrics["posted_time"] = created_at
                        except Exception:
                            pass

                    # Caption text (DOM fallback)
                    cap = None
                    for sel in [
                        "[data-e2e='browse-video-desc']",
                        "[data-e2e='video-desc']",
                        "h1",
                        "[class*='Desc']",
                    ]:
                        try:
                            cap = page.locator(sel).first.inner_text(timeout=1500)
                            if cap and cap.strip():
                                break
                        except Exception:
                            cap = None
                    if cap:
                        text = _clean_text(cap)
                        title = (text[:80] + "…") if len(text) > 80 else text

                    # If creator wasn't found in JSON, try from URL / DOM
                    if "creator" not in metrics:
                        m = re.search(r"tiktok\.com/@([^/]+)/video/", url)
                        if m:
                            metrics["creator"] = m.group(1)
                        else:
                            try:
                                href = page.locator("a[href^='https://www.tiktok.com/@']").first.get_attribute(
                                    "href", timeout=1200
                                )
                                if href:
                                    m2 = re.search(r"tiktok\.com/@([^/?#]+)", href)
                                    if m2:
                                        metrics["creator"] = m2.group(1)
                            except Exception:
                                pass

                    # Hashtags: derive from caption if needed
                    if "hashtags" not in metrics:
                        tags = _hashtags_from_text(text)
                        if tags:
                            metrics["hashtags"] = tags

                    # Sound: DOM fallback if needed
                    if "sound_title" not in metrics and "sound_artist" not in metrics:
                        snd_txt = None
                        for sel in ["[data-e2e='browse-music']", "a[href*='/music/']"]:
                            try:
                                snd_txt = page.locator(sel).first.inner_text(timeout=1200)
                                if snd_txt and snd_txt.strip():
                                    break
                            except Exception:
                                snd_txt = None
                        st, sa = _parse_sound_text(snd_txt)
                        if st:
                            metrics["sound_title"] = st
                        if sa:
                            metrics["sound_artist"] = sa

                    # Posted time: DOM fallback if needed
                    if "posted_time" not in metrics:
                        try:
                            tnodes = page.eval_on_selector_all(
                                "time",
                                """els => els.map(e => ({dt: e.getAttribute('datetime')||'', tx: (e.innerText||'')})).slice(0,5)""",
                            )
                            for t in tnodes or []:
                                dt = _clean_text(t.get("dt") or "")
                                tx = _clean_text(t.get("tx") or "")
                                if dt:
                                    metrics["posted_time"] = dt
                                    break
                                if tx and len(tx) <= 64:
                                    metrics["posted_time"] = tx
                                    break
                        except Exception:
                            pass

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

                    # Compute item_id (used for screenshots folder). Use URL-only so the id is stable
                    # even if TikTok caption/title text changes between runs.
                    item_id = stable_id(self.name, url)

                    # Screenshots (always)
                    try:
                        page.wait_for_selector("video", timeout=5000)
                    except Exception:
                        pass

                    shot_dir = os.path.abspath(os.path.join("./data/screenshots", item_id))
                    os.makedirs(shot_dir, exist_ok=True)
                    shots: list[str] = []

                    def _video_state() -> dict:
                        try:
                            return page.eval_on_selector(
                                "video",
                                """v => ({
                                  ended: !!v.ended,
                                  currentTime: Number(v.currentTime || 0),
                                  duration: Number(v.duration || 0),
                                  paused: !!v.paused
                                })""",
                            ) or {}
                        except Exception:
                            return {}

                    prev_t: float | None = None
                    for i in range(effective_count):
                        if i > 0:
                            page.wait_for_timeout(int(screenshot_interval_sec * 1000))

                        st = _video_state()
                        ct = None
                        try:
                            ct = float(st.get("currentTime"))
                        except Exception:
                            ct = None

                        # Stop early if the video ended.
                        if st.get("ended") is True:
                            break

                        # Stop early if we detect a loop (currentTime drops significantly).
                        if prev_t is not None and ct is not None and (ct + 0.25) < prev_t:
                            break

                        fn = f"frame_{i+1:02d}.png"
                        abs_path = os.path.join(shot_dir, fn)
                        try:
                            page.screenshot(path=abs_path)
                            shots.append(_relpath_posix(abs_path))
                        except Exception:
                            break

                        if ct is not None:
                            prev_t = ct
                    # Always store the list (may be empty if screenshotting failed).
                    metrics["screenshots"] = shots

                except Exception:
                    # If navigation fails, keep the minimal data.
                    item_id = stable_id(self.name, url)

                out.append(
                    Item(
                        item_id=item_id,
                        source=self.name,
                        url=url,
                        title=title,
                        text=text,
                        metrics=metrics,
                        created_at=created_at,
                        fetched_at=now,
                        raw={"url": url, "anchor_text": anchor_text, "search_url": search_url},
                    )
                )

            try:
                browser.close()
            except Exception:
                pass

        return out
