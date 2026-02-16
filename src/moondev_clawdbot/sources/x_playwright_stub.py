"""Optional X/Twitter following-timeline alpha scanner via browser automation (stub).

The video’s job B:
- opens the user’s following timeline
- filters posts with ~100+ likes
- extracts brands/tickers/companies + engagement
- stores JSON/CSV signals for the dashboard

X scraping also tends to require a signed-in session.
This repo ships `x_mock.py` by default to stay credential-free.

If you extend this:
- prefer a persistent browser profile you manually log into
- read visible engagement counts from the DOM
- emit normalized `Item`s
"""

from __future__ import annotations

from .base import Source


class XPlaywrightSource(Source):
    name = "x_playwright"

    def fetch(self):  # pragma: no cover
        raise NotImplementedError(
            "XPlaywrightSource is a stub. Use XMockSource (default) or implement your own Playwright scraper."
        )
