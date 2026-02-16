# Architecture (extracted from `moondev_clawdbot.mp4`)

## What the video describes (workflow)

The video describes an **automated “social arbitrage” system** inspired by Chris Camillo (Dumb Money):

### A) TikTok trend scanner (core)

Runs continuously (example cadence: **every 5 minutes**) and:

1. **Opens TikTok** (requires signing in).
2. **Rotates search keywords** to influence/shift what the “For You” page and search results show.
3. **Scrolls through ~5–10 videos per cycle** (the speaker also mentions going deeper e.g. ~200 videos per scan for search).
4. For each video, collects **5+ data points**:
   - views / likes / comments / shares
   - **view velocity** (momentum)
   - caption + hashtags
   - recency (speaker mentions filtering to “**this week**” because older viral videos can appear in search)
5. **Detects brands/companies** mentioned in captions/hashtags.
6. Runs an **“investable check”**:
   - if publicly traded → attach **ticker**
   - if private but owned by public co → attach **parent**
   - if “pre-IPO” → mark it
   - otherwise it can skip
7. Computes a **confidence score** (ranking).
8. Writes outputs to a **data folder** (speaker mentions **JSON + CSV**) and shows everything on a dashboard.

### B) Twitter/X “alpha scanner” (bonus)

A second job monitors the user’s following timeline, finds **high engagement posts** (example threshold: **100+ likes**), extracts:

- brands / tickers / companies
- engagement metrics

…and stores them similarly for the dashboard.

### C) Dashboard

The original project described in the video uses:

- a **vanilla JS** UI: `dashboard/index.html`
- a minimal API server: `server.js`
- no frameworks
- default port mentioned: **3456** (configurable)

The automation itself is orchestrated via **cron jobs** in the OpenClaw ecosystem.


## How this repo maps to the video

This repo reimplements the same *architecture* locally, but keeps all auth behind env vars and provides safe defaults.

### Implemented components

- **Cron-like scheduling**: `moondev-clawdbot run daemon` (or you can use real `cron`)
- **Keyword rotation**: `src/moondev_clawdbot/keywords.py` + `config/keywords.txt`
- **TikTok scanner (mock)**: `src/moondev_clawdbot/sources/tiktok_mock.py`
  - reads `config/tiktok_seed.jsonl` if you provide it
  - otherwise generates mock “viral video” items
- **Twitter alpha scanner (mock)**: `src/moondev_clawdbot/sources/x_mock.py`
  - reads `config/x_seed.jsonl` if you provide it
  - otherwise generates mock “high engagement” posts
- **Brand/ticker extraction**: `src/moondev_clawdbot/enrich.py`
  - tickers: regex (`$TSLA`, `NASDAQ:NVDA`, …)
  - brands: string match from `config/brands.txt`
- **Investable check**: `src/moondev_clawdbot/investable.py` + `config/investable_map.csv`
  - maps brand → (status, ticker, parent)
- **Confidence scoring**: `src/moondev_clawdbot/score.py`
  - engagement + recency + keyword match
  - TikTok emphasis: **view velocity**
  - investable boost
- **Storage**: SQLite (`src/moondev_clawdbot/storage.py`)
- **JSON/CSV outputs**: `moondev-clawdbot export` → `data/reports/*`
- **Dashboard (matches video)**: `server.js` + `dashboard/index.html`
- **Extra dashboard (convenience)**: Streamlit (`moondev-clawdbot ui`)

### What’s intentionally placeholder

- Real TikTok/X scraping via browser automation (login, anti-bot, ToS sensitivity).
  - The video relies on OpenClaw + a connected browser session.
  - This repo keeps those as **seed-file inputs** by default, so it runs without credentials.
