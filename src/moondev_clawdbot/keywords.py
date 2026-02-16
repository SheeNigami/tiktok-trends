from __future__ import annotations

import json
from pathlib import Path


def load_keywords(path: str = "./config/keywords.txt") -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    kws = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        kws.append(ln)
    return kws


def next_keyword(
    keywords_path: str = "./config/keywords.txt",
    state_path: str = "./data/keyword_state.json",
) -> str | None:
    kws = load_keywords(keywords_path)
    if not kws:
        return None

    sp = Path(state_path)
    idx = -1
    if sp.exists():
        try:
            idx = int(json.loads(sp.read_text(encoding="utf-8")).get("idx", -1))
        except Exception:
            idx = -1

    idx = (idx + 1) % len(kws)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({"idx": idx, "keyword": kws[idx]}, indent=2), encoding="utf-8")
    return kws[idx]
