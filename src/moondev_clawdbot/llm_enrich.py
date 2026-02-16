from __future__ import annotations

"""LLM enrichment (batch job mode).

Design goals (per requirements):
- Ingest runtime should NOT require or use OPENAI_API_KEY.
- Enrichment is a separate batch step that can use a vision-capable LLM.
- Provider is pluggable:
  - future: OpenAI vision API behind env var
  - now: placeholder runner for internal Codex OAuth / manual execution

This module returns *patches* to merge into metrics_json.
"""

import base64
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_MODEL = os.getenv("LLM_ENRICH_MODEL", "gpt-4o-mini")


def _read_image_b64(path: str, max_bytes: int = 3_500_000) -> str | None:
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return None
        data = p.read_bytes()
        if len(data) > max_bytes:
            # don't blow up payloads
            data = data[:max_bytes]
        return base64.b64encode(data).decode("ascii")
    except Exception:
        return None


def _openai_client() -> Any | None:
    """Return OpenAI client if explicitly enabled.

    IMPORTANT: we keep this behind LLM_ENRICH_PROVIDER=openai so runtime ingest
    never accidentally uses OPENAI_API_KEY.
    """
    if (os.getenv("LLM_ENRICH_PROVIDER") or "").lower() not in ("openai", "openai_vision"):
        return None

    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        return None

    try:
        from openai import OpenAI  # type: ignore

        return OpenAI()
    except Exception:
        return None


def _safe_json_from_text(s: str) -> dict[str, Any] | None:
    if not s:
        return None
    s = s.strip()
    try:
        j = json.loads(s)
        if isinstance(j, dict):
            return j
    except Exception:
        pass
    # best-effort: extract JSON object
    import re

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


def build_enrich_prompt(payload: dict[str, Any]) -> tuple[str, str]:
    system = (
        "You are a financial + culture trend analyst. "
        "You will be given a short-form video post (TikTok-style) plus screenshots. "
        "Use BOTH text and images to infer what the post is about. "
        "Return ONLY valid JSON."
    )

    user = (
        "Analyze the post and produce JSON with these keys:\n"
        "- context_summary: 1-2 sentences summarizing the trend/context (general, not just brands)\n"
        "- key_entities: list of entities (brands/products/people/places/memes/events)\n"
        "- related_assets: list of objects {symbol: string, type: 'stock'|'crypto'|'event', confidence: number 0..1, reason: string}\n"
        "- why_spreading: 1-2 sentences explaining why it is spreading\n"
        "- risk_flags: object {ad_sponsored: boolean, misinformation_or_medical_claim: boolean, notes: string}\n"
        "Rules: if unsure, keep confidence low and avoid hallucinating specifics.\n\n"
        f"INPUT_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    return system, user


def enrich_with_openai_vision(
    *,
    title: str | None,
    text: str | None,
    creator: str | None,
    hashtags: list[str] | None,
    sound_title: str | None,
    sound_artist: str | None,
    screenshot_paths: list[str],
    url: str | None,
    model: str | None = None,
) -> dict[str, Any] | None:
    client = _openai_client()
    if client is None:
        return None

    model = model or DEFAULT_MODEL

    # Build multimodal content
    content: list[dict[str, Any]] = []

    payload = {
        "title": title,
        "text": text,
        "creator": creator,
        "hashtags": hashtags,
        "sound": {"title": sound_title, "artist": sound_artist},
        "url": url,
    }

    system, user = build_enrich_prompt(payload)

    content.append({"type": "text", "text": user})

    # Attach up to 5 images
    for p in screenshot_paths[:5]:
        b64 = _read_image_b64(p)
        if not b64:
            continue
        # TikTok screenshots are PNG
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        out = resp.choices[0].message.content or ""
        return _safe_json_from_text(out)
    except Exception:
        return None


def enrich_with_codex_placeholder(
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Placeholder for internal Codex OAuth / batch runner.

    In this repo we cannot assume availability of internal auth, so this returns None.

    You can implement your internal runner to call a vision model here and return the
    JSON patch.
    """

    if (os.getenv("LLM_ENRICH_PROVIDER") or "").lower() in ("codex", "codex_oauth", "internal"):
        return {
            "enrich_method": "codex_placeholder",
            "enrich_note": "LLM_ENRICH_PROVIDER=codex selected, but internal runner not wired in this repo yet.",
        }
    return None


def normalize_llm_output(j: dict[str, Any]) -> dict[str, Any]:
    """Normalize model output to stable metrics keys."""
    out: dict[str, Any] = {}
    out["context_summary"] = j.get("context_summary")
    out["key_entities"] = j.get("key_entities") or j.get("entities")
    out["why_spreading"] = j.get("why_spreading")

    # Allow older name "related_tickers" or new "related_assets"
    rel = j.get("related_assets") or j.get("related_tickers")
    if rel is not None:
        out["related_assets"] = rel

    rf = j.get("risk_flags")
    if rf is not None:
        out["risk_flags"] = rf

    # Drop Nones
    out = {k: v for k, v in out.items() if v is not None}
    return out
