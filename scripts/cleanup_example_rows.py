#!/usr/bin/env python3
"""Cleanup helper for removing placeholder/example rows from the SQLite DB.

This repo ships with mock TikTok items that use example URLs like:
  https://www.tiktok.com/@example/video/111

Those are useful for a first run, but if you switched to the Playwright collector,
those old rows can stick around and keep showing up in the dashboard.

By default this script is DRY-RUN. It will NOT delete anything unless you pass
--apply.

Usage:
  python3 scripts/cleanup_example_rows.py --db ./data/clawdbot.sqlite
  python3 scripts/cleanup_example_rows.py --db ./data/clawdbot.sqlite --apply

You can also run the equivalent SQL manually:
  sqlite3 ./data/clawdbot.sqlite "DELETE FROM items WHERE source='tiktok' AND url LIKE '%tiktok.com/@example/%';"
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="./data/clawdbot.sqlite", help="Path to clawdbot sqlite DB")
    ap.add_argument(
        "--like",
        default="%tiktok.com/@example/%",
        help="SQL LIKE pattern to match URLs to delete (default: %(default)s)",
    )
    ap.add_argument("--source", default="tiktok", help="Only delete from this source (default: %(default)s)")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete rows (otherwise: dry-run)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=20,
        help="How many matching rows to print as a preview",
    )
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    where = "source = ? AND url LIKE ?"
    params = (args.source, args.like)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        cur = conn.execute(f"SELECT COUNT(*) AS n FROM items WHERE {where}", params)
        n = int(cur.fetchone()["n"])

        print(f"DB: {db_path}")
        print(f"Match: items WHERE {where}  params={params}")
        print(f"Matching rows: {n}")

        if n:
            print("\nPreview:")
            rows = conn.execute(
                f"SELECT item_id, source, url, title, fetched_at, score FROM items WHERE {where} ORDER BY fetched_at DESC LIMIT ?",
                params + (int(args.limit),),
            ).fetchall()
            for r in rows:
                print(f"- {r['fetched_at']}  score={r['score']}  {r['url']}  title={r['title']!r}")

        if not args.apply:
            print("\nDry-run only. Re-run with --apply to delete.")
            return 0

        if not n:
            print("\nNothing to delete.")
            return 0

        with conn:
            conn.execute(f"DELETE FROM items WHERE {where}", params)

        print(f"\nDeleted {n} rows.")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
