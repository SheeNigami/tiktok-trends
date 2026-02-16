from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

import streamlit as st


def conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def load_items(db_path: str, limit: int, min_score: float):
    with conn(db_path) as c:
        rows = c.execute(
            """
            SELECT * FROM items
            WHERE score IS NOT NULL AND score >= ?
            ORDER BY score DESC, fetched_at DESC
            LIMIT ?
            """,
            (min_score, limit),
        ).fetchall()
    return [dict(r) for r in rows]


st.set_page_config(page_title="MoonDev Clawdbot", layout="wide")

st.title("MoonDev Clawdbot – Social Arbitrage Feed")

db_path = os.getenv("CLAWDBOT_DB_PATH", "./data/clawdbot.sqlite")

col1, col2, col3 = st.columns(3)
with col1:
    min_score = st.slider("Min score", 0.0, 1.0, 0.65, 0.01)
with col2:
    limit = st.number_input("Max items", min_value=1, max_value=500, value=50, step=10)
with col3:
    st.caption(f"DB: `{db_path}`")

items = load_items(db_path, limit=int(limit), min_score=float(min_score))
st.write(f"Showing **{len(items)}** items")

for r in items:
    score = r.get("score")
    title = r.get("title")
    url = r.get("url")
    source = r.get("source")
    fetched_at = r.get("fetched_at")

    with st.expander(f"[{source}] {score:.2f} – {title}"):
        st.write(url)
        st.caption(f"fetched_at: {fetched_at}")

        metrics = {}
        try:
            metrics = json.loads(r.get("metrics_json") or "{}")
        except Exception:
            metrics = {}
        st.json(metrics)

        breakdown = {}
        try:
            breakdown = json.loads(r.get("score_breakdown_json") or "{}")
        except Exception:
            breakdown = {}
        if breakdown:
            st.subheader("Score breakdown")
            st.json(breakdown)

        if r.get("text"):
            st.subheader("Text")
            st.write(r.get("text"))
