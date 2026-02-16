from __future__ import annotations

from typing import Iterable
from rich.console import Console

from .sources.registry import make_sources
from .storage import Store
from .models import Item
from .score import score_items
from .enrich import enrich_items


console = Console()


def ingest(db_path: str, source_names: list[str]) -> int:
    store = Store(db_path)
    sources = make_sources(source_names)
    all_items: list[Item] = []
    for s in sources:
        console.print(f"[bold]Fetching[/bold] {s.name}...")
        items = s.fetch()
        console.print(f"  got {len(items)}")
        all_items.extend(items)
    all_items = enrich_items(all_items)
    n = store.upsert_items(all_items)
    console.print(f"[green]Upserted[/green] {n} items")
    return n


def score(db_path: str, limit: int = 200) -> int:
    store = Store(db_path)
    rows = store.fetch_unscored(limit=limit)
    items: list[Item] = []
    import json
    for r in rows:
        metrics = {}
        try:
            metrics = json.loads(r["metrics_json"] or "{}")
        except Exception:
            metrics = {}
        items.append(
            Item(
                item_id=r["item_id"],
                source=r["source"],
                url=r["url"],
                title=r["title"],
                text=r["text"],
                metrics=metrics,
                created_at=r["created_at"],
                fetched_at=r["fetched_at"],
                raw=None,
            )
        )
    scored = score_items(items)
    n = store.update_scores(scored)
    console.print(f"[green]Scored[/green] {n} items")
    return n
