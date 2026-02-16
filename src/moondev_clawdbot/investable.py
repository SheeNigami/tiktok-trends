from __future__ import annotations

import csv
from pathlib import Path


def load_investable_map(path: str = "./config/investable_map.csv") -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    with open(p, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            brand = (row.get("brand") or "").strip()
            if not brand:
                continue
            out[brand.lower()] = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
    return out


def investable_info_for_brand(brand: str, m: dict[str, dict]) -> dict | None:
    if not brand:
        return None
    return m.get(brand.lower())
