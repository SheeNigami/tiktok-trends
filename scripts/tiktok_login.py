#!/usr/bin/env python3
"""Open a persistent Playwright Chromium profile for TikTok login.

This script does NOT scrape. It just opens TikTok in a persistent context so you
can log in once, then close the window.

Usage:
  source .venv/bin/activate
  python scripts/tiktok_login.py

After login, you can run the collector headless.
"""

from __future__ import annotations

import os


def main() -> None:
    from playwright.sync_api import sync_playwright  # type: ignore

    locale = os.getenv("TIKTOK_LOCALE", "en")
    user_data_dir = os.path.abspath("./data/playwright/tiktok_profile")
    os.makedirs(user_data_dir, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            viewport={"width": 1280, "height": 800},
            locale=locale,
        )
        page = ctx.new_page()
        page.set_default_timeout(30_000)
        page.goto("https://www.tiktok.com/", wait_until="domcontentloaded")

        print("\n[TikTok login]")
        print("1) In the opened Chromium window, click Log in and complete verification.")
        print("2) After you see the feed/search normally, close the window.")
        print("   (Cookies persist in ./data/playwright/tiktok_profile)\n")

        try:
            page.wait_for_timeout(10_000_000)  # ~2.7 hours; close window to end
        except KeyboardInterrupt:
            pass
        finally:
            try:
                ctx.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
