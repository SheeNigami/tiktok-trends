from __future__ import annotations

import csv
import json
from pathlib import Path
from datetime import datetime, timezone

from .storage import Store


def export_reports(db_path: str, out_dir: str = "./data/reports", limit: int = 100, min_score: float = 0.0) -> tuple[str, str]:
    store = Store(db_path)
    rows = store.top_items(limit=limit, min_score=min_score)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)

    json_path = str(outp / f"signals_{ts}.json")
    csv_path = str(outp / f"signals_{ts}.csv")

    Path(json_path).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    # Flatten some fields for CSV
    fields = ["item_id", "source", "score", "title", "url", "created_at", "fetched_at", "metrics_json"]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})

    return json_path, csv_path
