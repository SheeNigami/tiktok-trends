from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable
import json
from datetime import datetime, timezone

from .models import Item


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  item_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT,
  metrics_json TEXT NOT NULL,
  score REAL,
  score_breakdown_json TEXT,
  created_at TEXT,
  fetched_at TEXT NOT NULL,
  raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_score ON items(score);
CREATE INDEX IF NOT EXISTS idx_items_fetched_at ON items(fetched_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path))
        self._ensure()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def upsert_items(self, items: Iterable[Item]) -> int:
        n = 0
        with self._conn() as conn:
            for it in items:
                fetched_at = it.fetched_at or now_iso()
                conn.execute(
                    """
                    INSERT INTO items(item_id, source, url, title, text, metrics_json, score, score_breakdown_json, created_at, fetched_at, raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(item_id) DO UPDATE SET
                      title=excluded.title,
                      text=excluded.text,
                      metrics_json=excluded.metrics_json,
                      score=COALESCE(excluded.score, items.score),
                      score_breakdown_json=COALESCE(excluded.score_breakdown_json, items.score_breakdown_json),
                      fetched_at=excluded.fetched_at,
                      raw_json=COALESCE(excluded.raw_json, items.raw_json)
                    """,
                    (
                        it.item_id,
                        it.source,
                        it.url,
                        it.title,
                        it.text,
                        json.dumps(it.metrics or {}, ensure_ascii=False),
                        it.score,
                        json.dumps(it.score_breakdown or {}, ensure_ascii=False) if it.score_breakdown else None,
                        it.created_at,
                        fetched_at,
                        json.dumps(it.raw or {}, ensure_ascii=False) if it.raw else None,
                    ),
                )
                n += 1
        return n

    def update_scores(self, scored: Iterable[Item]) -> int:
        n = 0
        with self._conn() as conn:
            for it in scored:
                conn.execute(
                    "UPDATE items SET score=?, score_breakdown_json=? WHERE item_id=?",
                    (
                        it.score,
                        json.dumps(it.score_breakdown or {}, ensure_ascii=False),
                        it.item_id,
                    ),
                )
                n += 1
        return n

    def fetch_unscored(self, limit: int = 200):
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM items WHERE score IS NULL ORDER BY fetched_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def top_items(self, limit: int = 50, min_score: float | None = None):
        q = "SELECT * FROM items"
        params = []
        if min_score is not None:
            q += " WHERE score IS NOT NULL AND score >= ?"
            params.append(min_score)
        # SQLite NULL ordering can be surprising; force scored items first.
        q += " ORDER BY (score IS NULL) ASC, score DESC, fetched_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
