from __future__ import annotations

import json
import os
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
    for tk in tickers:
        related.append({"ticker": tk, "confidence": 0.35, "reason": "Mentioned in text."})

    it.metrics = dict(it.metrics or {})
    if tickers:
        it.metrics["tickers"] = tickers
    if brand_hits:
        it.metrics["brands"] = brand_hits

    it.metrics.setdefault("context_summary", context)
    it.metrics.setdefault("key_entities", key_entities)
    it.metrics.setdefault("related_tickers", related)
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


def _ocr_text_from_screenshots(rel_paths: list[str], max_images: int = 2, max_chars: int = 2500) -> str | None:
    """Best-effort OCR for TikTok screenshots.

    Returns extracted text or None if OCR isn't available.
    """
    if not rel_paths:
        return None

    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore
    except Exception:
        return None

    # Confirm tesseract binary exists
    try:
        _ = pytesseract.get_tesseract_version()  # noqa: F841
    except Exception:
        return None

    chunks: list[str] = []
    for rp in rel_paths[: max_images]:
        ap = os.path.abspath(rp)
        if not os.path.exists(ap):
            continue
        try:
            with Image.open(ap) as im:
                txt = pytesseract.image_to_string(im)
            txt = re.sub(r"\s+", " ", (txt or "").strip())
            if txt:
                chunks.append(txt)
        except Exception:
            continue

    if not chunks:
        return None

    out = "\n".join(chunks)
    if len(out) > max_chars:
        out = out[:max_chars] + "…"
    return out


def _openai_client() -> Any | None:
    """Return an OpenAI client if configured, else None."""
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        return None

    # openai>=1
    try:
        from openai import OpenAI  # type: ignore

        return OpenAI()
    except Exception:
        pass

    # legacy openai
    try:  # pragma: no cover
        import openai  # type: ignore

        return openai
    except Exception:
        return None


def _safe_json_from_text(s: str) -> dict[str, Any] | None:
    if not s:
        return None
    s = s.strip()

    # Try direct
    try:
        j = json.loads(s)
        if isinstance(j, dict):
            return j
    except Exception:
        pass

    # Try to extract first JSON object substring
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None
    try:
        j = json.loads(m.group(0))
        if isinstance(j, dict):
            return j
    except Exception:
        return None
    return None


def enrich_item_llm(it: Item) -> Item:
    """LLM-based enrichment (optional).

    If OPENAI_API_KEY is set AND the `openai` package is installed, this will call
    OpenAI Chat Completions and attach structured fields into metrics.

    Otherwise, this function is a no-op.
    """

    client = _openai_client()
    if client is None:
        return it

    m = dict(it.metrics or {})
    creator = m.get("creator")
    hashtags = m.get("hashtags")
    sound_title = m.get("sound_title")
    sound_artist = m.get("sound_artist")
    screenshots = m.get("screenshots") if isinstance(m.get("screenshots"), list) else []

    ocr_text = None
    try:
        ocr_text = _ocr_text_from_screenshots([str(x) for x in screenshots if x])
    except Exception:
        ocr_text = None

    blob = {
        "title": it.title,
        "text": it.text,
        "creator": creator,
        "hashtags": hashtags,
        "sound": {"title": sound_title, "artist": sound_artist},
        "ocr": ocr_text,
        "url": it.url,
        "source": it.source,
    }

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    system = (
        "You are a financial/social trend analyst. "
        "Given a TikTok-style post and metadata, produce a compact structured enrichment. "
        "Return ONLY valid JSON with the exact keys requested."
    )

    user = (
        "Enrich this social post with:\n"
        "- context_summary: 1-2 sentences explaining the trend/context\n"
        "- key_entities: list of brands/products/people/places (strings)\n"
        "- related_tickers: list of objects {ticker: string, confidence: number 0..1, reason: string}\n"
        "- why_spreading: 1-2 sentences (mechanism: meme, controversy, utility, deal, etc.)\n"
        "- risk_flags: object {ad_sponsored: boolean, misinformation_or_medical_claim: boolean, notes: string}\n"
        "If you are unsure, keep confidence low and keep fields empty rather than hallucinating.\n\n"
        f"INPUT:\n{json.dumps(blob, ensure_ascii=False)}"
    )

    # Call OpenAI: support both openai>=1 client and legacy module
    content = None
    try:
        if hasattr(client, "chat") and hasattr(client.chat, "completions"):
            # openai>=1
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
            except Exception:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.2,
                )
            content = resp.choices[0].message.content
        else:  # pragma: no cover
            # legacy openai
            resp = client.ChatCompletion.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
            )
            content = resp["choices"][0]["message"]["content"]
    except Exception:
        return it

    j = _safe_json_from_text(str(content or ""))
    if not j:
        return it

    it.metrics = dict(it.metrics or {})
    it.metrics.update(
        {
            "context_summary": j.get("context_summary") or it.metrics.get("context_summary"),
            "key_entities": j.get("key_entities") or j.get("entities") or None,
            "related_tickers": j.get("related_tickers") or None,
            "why_spreading": j.get("why_spreading") or None,
            "risk_flags": j.get("risk_flags") or None,
            "enrich_method": "openai",
            "enrich_model": model,
        }
    )

    # avoid storing huge OCR text, but keep that we used it
    if ocr_text:
        it.metrics.setdefault("ocr_used", True)

    # Clean Nones
    it.metrics = {k: v for k, v in it.metrics.items() if v is not None}

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
