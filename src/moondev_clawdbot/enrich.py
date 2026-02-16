from __future__ import annotations

import re
from pathlib import Path

from .models import Item
from .investable import load_investable_map, investable_info_for_brand


TICKER_RE = re.compile(r"\$(?P<t>[A-Z]{1,6})\b")
EXCHANGE_RE = re.compile(r"\b(?:NASDAQ|NYSE)\s*:\s*(?P<t>[A-Z]{1,6})\b", re.I)


def load_brands(path: str = "./config/brands.txt") -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    brands = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        brands.append(ln)
    return brands


def extract_tickers(text: str) -> list[str]:
    out = set()
    for m in TICKER_RE.finditer(text):
        out.add(m.group("t"))
    for m in EXCHANGE_RE.finditer(text):
        out.add(m.group("t").upper())
    return sorted(out)


def extract_brands(text: str, brands: list[str]) -> list[str]:
    t = text.lower()
    hits = []
    for b in brands:
        if b.lower() in t:
            hits.append(b)
    return sorted(set(hits))


def enrich_item(it: Item, brands: list[str] | None = None) -> Item:
    blob = (it.title or "") + "\n" + (it.text or "")
    brands = brands or []
    tickers = extract_tickers(blob)
    brand_hits = extract_brands(blob, brands)

    it.metrics = dict(it.metrics or {})
    if tickers:
        it.metrics["tickers"] = tickers
    if brand_hits:
        it.metrics["brands"] = brand_hits
    return it


def enrich_items(
    items: list[Item],
    brands_path: str = "./config/brands.txt",
    investable_map_path: str = "./config/investable_map.csv",
) -> list[Item]:
    brands = load_brands(brands_path)
    inv = load_investable_map(investable_map_path)

    out: list[Item] = []
    for it in items:
        it = enrich_item(it, brands=brands)
        # Attach investable mapping for any detected brands
        b = (it.metrics or {}).get("brands") or []
        infos = []
        for brand in b:
            info = investable_info_for_brand(brand, inv)
            if info:
                infos.append(info)
        if infos:
            it.metrics = dict(it.metrics or {})
            it.metrics["investable"] = infos
        out.append(it)
    return out
