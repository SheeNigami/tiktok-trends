from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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


def enrich_item_regex(it: Item, brands: list[str] | None = None) -> Item:
    """Lightweight, offline enrichment (regex/keyword-based).

    This is the fallback path when no LLM is configured.
    Produces the same *shape* of fields as the LLM enrich, just with heuristics.
    """
    blob = (it.title or "") + "\n" + (it.text or "")
    brands = brands or []
    tickers = extract_tickers(blob)
    brand_hits = extract_brands(blob, brands)

    t = blob.lower()

    # risk flags (simple heuristics)
    ad_sponsored = bool(re.search(r"\b#ad\b|\bsponsored\b|paid partnership|promo code|use code\b", t))
    medical = bool(
        re.search(
            r"\bcure\b|\btreat\b|\bdiagnos\w*\b|\bdoctor\b|\bmedic\w*\b|\bvaccine\b|\bivermectin\b|\bmiracle\b",
            t,
        )
    )

    why = None
    if re.search(r"\bviral\b|\btrend\w*\b|\bblowing up\b|\beveryone\s+is\s+talking\b", t):
        why = "Viral/trend propagation across the feed."
    elif re.search(r"\bhaul\b|\bunboxing\b|\breview\b|\bdupe\b", t):
        why = "Product content (haul/review/dupe) is easy to remix and share."
    elif re.search(r"\bdeal\b|\bsale\b|\bdiscount\b|\bcoupon\b|\bpromo\b|\bback in stock\b", t):
        why = "People are sharing it as a deal / availability signal."

    # minimal context summary fallback (first 1-2 sentences)
    context = None
    if blob.strip():
        s = re.split(r"(?<=[.!?])\s+", blob.strip())
        context = " ".join(s[:2])[:280]

    key_entities = []
    key_entities.extend(brand_hits)
    key_entities.extend([x for x in tickers])
    # keep small
    key_entities = list(dict.fromkeys([x for x in key_entities if x]))[:12]

    related = []
    related_assets = []
    for tk in tickers:
        related.append({"ticker": tk, "confidence": 0.35, "reason": "Mentioned in text."})
        related_assets.append({"symbol": tk, "type": "stock", "confidence": 0.35, "reason": "Mentioned in text."})

    it.metrics = dict(it.metrics or {})
    if tickers:
        it.metrics["tickers"] = tickers
    if brand_hits:
        it.metrics["brands"] = brand_hits

    it.metrics.setdefault("context_summary", context)
    it.metrics.setdefault("key_entities", key_entities)
    it.metrics.setdefault("related_tickers", related)
    it.metrics.setdefault("related_assets", related_assets)
    it.metrics.setdefault("why_spreading", why)
    it.metrics.setdefault(
        "risk_flags",
        {
            "ad_sponsored": bool(ad_sponsored),
            "misinformation_or_medical_claim": bool(medical),
            "notes": "Heuristic flags (offline).",
        },
    )

    it.metrics.setdefault("enrich_method", "regex")

    # Clean Nones
    it.metrics = {k: v for k, v in it.metrics.items() if v is not None}

    return it


# NOTE: LLM enrichment is intentionally NOT executed during ingest runtime.
# See `moondev-clawdbot enrich-llm` (batch job mode) which can use vision models
# and attach structured fields.


def enrich_items(
    items: list[Item],
    brands_path: str = "./config/brands.txt",
    investable_map_path: str = "./config/investable_map.csv",
) -> list[Item]:
    brands = load_brands(brands_path)
    inv = load_investable_map(investable_map_path)

    out: list[Item] = []
    for it in items:
        # Always run the offline regex enrichment first.
        it = enrich_item_regex(it, brands=brands)

        # Attach investable mapping for any detected brands.
        b = (it.metrics or {}).get("brands") or []
        infos = []
        for brand in b:
            info = investable_info_for_brand(brand, inv)
            if info:
                infos.append(info)
        if infos:
            it.metrics = dict(it.metrics or {})
            it.metrics["investable"] = infos

        # If we have investable mapping with tickers, add them to related_tickers (offline).
        inv_hits = (it.metrics or {}).get("investable") or []
        try:
            rel = list((it.metrics or {}).get("related_tickers") or [])
            for x in inv_hits:
                tk = (x or {}).get("ticker")
                br = (x or {}).get("brand")
                if tk:
                    rel.append(
                        {
                            "ticker": str(tk),
                            "confidence": 0.55,
                            "reason": f"Investable map: {br or 'brand'}.",
                        }
                    )
            # de-dupe by ticker
            seen = set()
            rel2 = []
            for r in rel:
                tkr = (r or {}).get("ticker")
                if not tkr or tkr in seen:
                    continue
                seen.add(tkr)
                rel2.append(r)
            if rel2:
                it.metrics = dict(it.metrics or {})
                it.metrics["related_tickers"] = rel2
        except Exception:
            pass

        # LLM enrichment is handled by a separate batch command (vision-first).
        out.append(it)
    return out
