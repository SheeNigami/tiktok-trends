from __future__ import annotations

"""Vision-first enrichment (batch).

Key constraints (project requirements):
- MUST work without credentials by default (no OPENAI_API_KEY required).
- MUST be vision-first: when using an actual model provider, send screenshots as images.
- Enrichment runs as a separate batch command (see CLI: `moondev-clawdbot enrich-vision`).
- Store output under metrics_json['llm_enrich'].

Providers:
- stub (default): deterministic offline enrichment that reads screenshot bytes.
- codex: placeholder hook for an internal Codex OAuth runner (not wired here).
- openai (optional): real vision model via OpenAI API (requires OPENAI_API_KEY + `openai` package).

The llm_enrich object shape is stable and dashboard-friendly.
"""

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from .models import Item
from .storage import Store, now_iso


AssetType = Literal["stock", "crypto", "event", "other"]


# -----------------------------
# helpers
# -----------------------------

def _sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def _safe_read_bytes(p: str) -> bytes | None:
    try:
        return Path(p).read_bytes()
    except Exception:
        return None


def _data_url_for_image(path: str, b: bytes) -> str:
    ext = (Path(path).suffix or ".png").lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "image/png")
    return f"data:{mime};base64,{base64.b64encode(b).decode('ascii')}"


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


_RISK_AD_RE = re.compile(r"\b(#ad|sponsored|paid\s+partnership|promo\s+code|affiliate)\b", re.I)
_RISK_MED_RE = re.compile(r"\b(cure|treats?|heals?|miracle|detox|weight\s*loss|medical\s+advice|diagnos(e|is))\b", re.I)
_RISK_SCAM_RE = re.compile(
    r"\b(giveaway|airdrop|dm\s+me|whatsapp|telegram|cash\s*app|guaranteed\s+profit|double\s+your|impersonat)\b",
    re.I,
)


def _detect_topic(blob: str) -> str:
    t = (blob or "").lower()
    if any(x in t for x in ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto", "memecoin"]):
        return "crypto"
    if re.search(r"\$[A-Z]{1,6}\b", blob or "") or any(x in t for x in ["nasdaq", "nyse", "earnings", "stock"]):
        return "stock"
    if any(x in t for x in ["election", "debate", "olympics", "coachella", "grammys", "super bowl"]):
        return "event"
    return "other"


def _entities_from_metrics(m: dict[str, Any]) -> list[str]:
    ents: list[str] = []

    for k in ("brands", "key_entities"):
        v = m.get(k)
        if isinstance(v, list):
            ents.extend([str(x) for x in v if x])

    if m.get("creator"):
        ents.append(f"@{m['creator']}")

    if isinstance(m.get("hashtags"), list):
        ents.extend([str(x) for x in m["hashtags"] if x])

    if m.get("sound_title"):
        ents.append(str(m.get("sound_title")))
    if m.get("sound_artist"):
        ents.append(str(m.get("sound_artist")))

    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for e in ents:
        e = _clean(e)
        if not e:
            continue
        k = e.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(e)

    return out[:25]


def _candidate(asset_type: AssetType, symbol: str | None, name: str, confidence: float, reason: str) -> dict[str, Any]:
    return {
        "asset_type": asset_type,
        "symbol": symbol,
        "name": name,
        "confidence": float(max(0.0, min(1.0, confidence))),
        "reason": reason,
    }


def _candidates_from_metrics(m: dict[str, Any], topic: str) -> list[dict[str, Any]]:
    cands: list[dict[str, Any]] = []

    inv = m.get("investable")
    if isinstance(inv, list):
        for x in inv:
            if not isinstance(x, dict):
                continue
            ticker = x.get("ticker")
            brand = x.get("brand") or x.get("parent") or ""
            if ticker:
                cands.append(_candidate("stock", str(ticker), str(brand or ticker), 0.75, "Investable map: brand→ticker."))

    if isinstance(m.get("tickers"), list):
        for t in m["tickers"]:
            if t:
                cands.append(_candidate("stock", str(t), str(t), 0.55, "Ticker appears in text."))

    # if earlier offline related_tickers exists, map into candidates
    rt = m.get("related_tickers")
    if isinstance(rt, list):
        for obj in rt:
            if not isinstance(obj, dict):
                continue
            t = obj.get("ticker")
            if not t:
                continue
            cands.append(
                _candidate(
                    "stock",
                    str(t),
                    str(t),
                    float(obj.get("confidence") or 0.4),
                    str(obj.get("reason") or "Related ticker (offline)."),
                )
            )

    # crypto heuristics only when topic indicates crypto
    if topic == "crypto":
        blob = (" ".join([str(x) for x in (m.get("hashtags") or [])]) + " " + str(m.get("context_summary") or "")).lower()
        if "bitcoin" in blob or "#btc" in blob or " btc" in blob:
            cands.append(_candidate("crypto", "BTC", "Bitcoin", 0.5, "Crypto topic suggests BTC."))
        if "ethereum" in blob or "#eth" in blob or " eth" in blob:
            cands.append(_candidate("crypto", "ETH", "Ethereum", 0.45, "Crypto topic suggests ETH."))

    # Ensure we always have *something* to display
    if not cands:
        cands.append(
            _candidate(
                "event" if topic == "event" else "other",
                None,
                "Viral short-form trend",
                0.2,
                "No explicit investable asset detected; treat as a general trend/event.",
            )
        )

    # de-dupe by (type,symbol,name)
    seen = set()
    uniq: list[dict[str, Any]] = []
    for c in cands:
        key = (c.get("asset_type"), c.get("symbol"), c.get("name"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    # sort by confidence desc
    uniq.sort(key=lambda x: float(x.get("confidence") or 0.0), reverse=True)
    return uniq[:10]


# -----------------------------
# providers
# -----------------------------

def vision_enrich_stub(it: Item, image_paths: list[str]) -> dict[str, Any]:
    """Deterministic offline enrichment.

    Reads screenshot bytes and derives stable fingerprints.
    """

    m = dict(it.metrics or {})
    blob = _clean((it.title or "") + "\n" + (it.text or ""))

    used: list[str] = []
    fps: list[str] = []
    for p in image_paths[:5]:
        b = _safe_read_bytes(p)
        if not b:
            continue
        used.append(p)
        fps.append(_sha12(b))

    topic = _detect_topic(blob)

    main_trend = None
    if isinstance(m.get("hashtags"), list) and m["hashtags"]:
        main_trend = str(m["hashtags"][0])
    elif m.get("keyword"):
        main_trend = str(m.get("keyword"))
    else:
        main_trend = (it.title or "(tiktok)")[:120]

    ad = bool(_RISK_AD_RE.search(blob))
    med = bool(_RISK_MED_RE.search(blob))
    scam = bool(_RISK_SCAM_RE.search(blob))

    notes: list[str] = []
    if ad:
        notes.append("ad/sponsored language")
    if med:
        notes.append("medical/health claim language")
    if scam:
        notes.append("giveaway/impersonation/scam language")

    entities = _entities_from_metrics(m)
    candidates = _candidates_from_metrics(m, topic)

    best = candidates[0] if candidates else {"asset_type": "other"}
    asset_type: AssetType = best.get("asset_type") if best.get("asset_type") in ("stock", "crypto", "event", "other") else "other"

    # Keep context human-readable (no internal fingerprints).
    context = f"topic={topic}"
    why = "Likely spreading due to algorithmic distribution + remixable formats/audio + social proof."

    return {
        "main_trend": main_trend,
        "context": context,
        "entities": entities,
        "why_spreading": why,
        "risk_flags": {
            "ad_sponsored": ad,
            "misinformation_or_medical_claim": med,
            "scam_or_impersonation": scam,
            "notes": ", ".join(notes) if notes else "",
        },
        "asset_type": asset_type,
        "candidates": candidates,
        "images_used": used,
        "provider": "stub",
        "model": None,
        "enriched_at": now_iso(),
    }


def _openai_client() -> Any | None:
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        return None
    try:
        from openai import OpenAI  # type: ignore

        return OpenAI()
    except Exception:
        return None


def vision_enrich_openai(it: Item, image_paths: list[str], *, model: str) -> dict[str, Any]:
    """Optional OpenAI vision enrichment.

    Sends screenshots as images (not OCR-only).
    """

    client = _openai_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY and openai package are required for provider=openai")

    m = dict(it.metrics or {})

    shots = []
    used: list[str] = []
    for p in image_paths[:5]:
        b = _safe_read_bytes(p)
        if not b:
            continue
        shots.append({"type": "image_url", "image_url": {"url": _data_url_for_image(p, b)}})
        used.append(p)

    blob = {
        "title": it.title,
        "text": it.text,
        "url": it.url,
        "creator": m.get("creator"),
        "hashtags": m.get("hashtags"),
        "sound": {"title": m.get("sound_title"), "artist": m.get("sound_artist")},
        "posted_time": m.get("posted_time"),
    }

    system = (
        "You are a financial/social trend analyst. "
        "Use the provided screenshots (vision) as primary evidence and the metadata as context. "
        "Return ONLY valid JSON."
    )

    user_text = (
        "Analyze the post and return JSON with keys:\n"
        "- main_trend (string)\n"
        "- context (string)\n"
        "- entities (array of strings)\n"
        "- why_spreading (string)\n"
        "- risk_flags {ad_sponsored:boolean, misinformation_or_medical_claim:boolean, scam_or_impersonation:boolean, notes:string}\n"
        "- asset_type: stock|crypto|event|other\n"
        "- candidates: array of {asset_type, symbol|null, name, confidence 0..1, reason}\n\n"
        "Rules: if unsure, keep confidence low and prefer event/other candidates rather than guessing tickers.\n\n"
        f"INPUT_METADATA_JSON: {json.dumps(blob, ensure_ascii=False)}"
    )

    msg = [{"type": "text", "text": user_text}, *shots]

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": msg},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    content = resp.choices[0].message.content or "{}"
    j = json.loads(content)
    if not isinstance(j, dict):
        raise RuntimeError("OpenAI returned non-object JSON")

    j["images_used"] = used
    j["provider"] = "openai"
    j["model"] = model
    j["enriched_at"] = now_iso()
    return j


# -----------------------------
# DB batch
# -----------------------------

def enrich_db_vision(
    db_path: str,
    *,
    limit: int = 50,
    provider: str = "stub",
    overwrite: bool = False,
    max_images: int = 5,
    source: str = "tiktok",
) -> int:
    """Batch enrich items in SQLite DB.

    Only items with screenshots are enriched.
    """

    store = Store(db_path)

    # Fetch more than limit because many rows may be non-TikTok or missing screenshots.
    rows = store.fetch_recent(limit=max(200, limit * 10), source=source)

    updated = 0
    for r in rows:
        item_id = r.get("item_id")
        if not item_id:
            continue

        try:
            metrics = json.loads(r.get("metrics_json") or "{}")
            if not isinstance(metrics, dict):
                metrics = {}
        except Exception:
            metrics = {}

        if (not overwrite) and isinstance(metrics.get("llm_enrich"), dict) and metrics.get("llm_enrich"):
            continue

        shots = metrics.get("screenshots") if isinstance(metrics.get("screenshots"), list) else []
        shots = [str(x) for x in shots if x]
        if not shots:
            continue

        image_paths = [os.path.abspath(p) for p in shots[:max_images]]

        it = Item(
            item_id=str(item_id),
            source=str(r.get("source") or source),
            url=str(r.get("url") or ""),
            title=str(r.get("title") or ""),
            text=r.get("text"),
            metrics=metrics,
            score=r.get("score"),
            created_at=r.get("created_at"),
            fetched_at=r.get("fetched_at"),
            raw=None,
        )

        prov = (provider or "stub").strip().lower()
        try:
            if prov in ("openai", "openai_vision"):
                model = os.getenv("VISION_ENRICH_MODEL") or os.getenv("OPENAI_MODEL") or os.getenv("LLM_ENRICH_MODEL") or "gpt-4o-mini"
                llm_enrich = vision_enrich_openai(it, image_paths, model=model)
            elif prov in ("codex", "internal"):
                # Placeholder: no internal runner is wired here.
                llm_enrich = vision_enrich_stub(it, image_paths)
                llm_enrich["provider"] = "codex_placeholder"
                llm_enrich["notes"] = "Provider=codex selected, but internal runner is not wired; used stub output."
            else:
                llm_enrich = vision_enrich_stub(it, image_paths)
        except Exception as e:
            llm_enrich = {
                "provider": prov,
                "model": os.getenv("VISION_ENRICH_MODEL") if prov.startswith("openai") else None,
                "enriched_at": now_iso(),
                "error": str(e),
                "images_used": image_paths,
            }

        # Merge into metrics_json
        if store.merge_metrics_json(str(item_id), {"llm_enrich": llm_enrich}, overwrite=False):
            updated += 1
        if updated >= limit:
            break

    return updated
