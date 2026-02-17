from __future__ import annotations

import json
import os
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


def load_keyword_groups(path: str = "./config/keyword_groups.json") -> dict:
    """Load keyword groups config.

    Shape:
      {"active": "groupname", "groups": {"groupname": ["kw1", ...]}}

    If file missing/invalid, returns an empty structure.
    """

    p = Path(path)
    if not p.exists():
        return {"active": "default", "groups": {}}
    try:
        j = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(j, dict):
            return {"active": "default", "groups": {}}
        active = str(j.get("active") or "default")
        groups = j.get("groups") if isinstance(j.get("groups"), dict) else {}
        # normalize
        norm = {}
        for k, v in (groups or {}).items():
            name = str(k).strip()
            if not name:
                continue
            if isinstance(v, list):
                kws = [str(x).strip() for x in v if str(x).strip() and not str(x).strip().startswith("#")]
            else:
                kws = [str(x).strip() for x in str(v).splitlines() if str(x).strip() and not str(x).strip().startswith("#")]
            norm[name] = kws
        return {"active": active, "groups": norm}
    except Exception:
        return {"active": "default", "groups": {}}


def next_keyword(
    keywords_path: str = "./config/keywords.txt",
    keyword_groups_path: str = "./config/keyword_groups.json",
    state_path: str = "./data/keyword_state.json",
    group: str | None = None,
) -> str | None:
    """Rotate to the next keyword.

    Preference order:
    - If keyword_groups.json exists and has an active group (or group override), rotate within that group.
    - Else, fall back to keywords.txt.

    State file keeps independent indices per group.
    """

    groups_cfg = load_keyword_groups(keyword_groups_path)
    groups = groups_cfg.get("groups") if isinstance(groups_cfg.get("groups"), dict) else {}

    active_group = (group or os.getenv("KEYWORD_GROUP") or groups_cfg.get("active") or "default")
    active_group = str(active_group).strip() or "default"

    kws = []
    if groups and active_group in groups:
        kws = list(groups.get(active_group) or [])
    if not kws:
        kws = load_keywords(keywords_path)
        active_group = "__flat__"

    if not kws:
        return None

    sp = Path(state_path)
    state = {}
    if sp.exists():
        try:
            state = json.loads(sp.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {}
        except Exception:
            state = {}

    idx_by_group = state.get("idx_by_group") if isinstance(state.get("idx_by_group"), dict) else {}
    # Back-compat: if old state had a single idx, use it for __flat__
    if "idx" in state and "__flat__" not in idx_by_group:
        try:
            idx_by_group["__flat__"] = int(state.get("idx", -1))
        except Exception:
            pass

    idx = int(idx_by_group.get(active_group, -1))
    idx = (idx + 1) % len(kws)
    idx_by_group[active_group] = idx

    payload = {
        "active_group": active_group,
        "idx_by_group": idx_by_group,
        "keyword": kws[idx],
    }
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return kws[idx]
