# MoonDev Clawdbot (local reimplementation)

This project is a **local, credential-free-by-default** reimplementation of the workflow described in the video `moondev_clawdbot.mp4`.

It implements a **social arbitrage pipeline**:

1. **Ingest** from multiple sources (**TikTok trend scan** (mock), Twitter/X alpha scan (mock), plus optional HN/RSS/Reddit)
2. **Normalize** into a single `Item` schema
3. **Score** items with a heuristic "confidence" model (engagement + recency + keyword match + view velocity)
4. **Store** into a local SQLite database
5. **Alert** (stdout by default; optional Telegram/Discord via env vars)
6. **Dashboard** via Streamlit *and* a vanilla JS dashboard (`server.js` + `dashboard/index.html`)

> Note: Any integrations that require credentials are implemented behind **environment variables** and are optional.

## Quickstart

### 0) Create a virtualenv

```bash
cd /Users/sheen/clawd/moondev_clawdbot_project
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

### 1) Configure env

Copy the example env file and edit it:

```bash
cp .env.example .env
```

### 2) (Optional) Provide seed data

By default, TikTok/X ingestion is mocked so the project runs without credentials.

If you want deterministic inputs, create seed files:

- `config/tiktok_seed.jsonl` (one JSON object per line)
- `config/x_seed.jsonl` (one JSON object per line)

Example line:

```json
{"url":"https://www.tiktok.com/@user/video/123","title":"Brand is everywhere","text":"caption + hashtags","metrics":{"views":123,"likes":45,"comments":6,"shares":7,"view_velocity":0.8}}
```

Keyword rotation is controlled by `config/keywords.txt` (the scanner rotates one keyword per run).

### 3) Run one pipeline cycle (ingest → score → alert)

```bash
moondev-clawdbot run once --sources tiktok,x_mock
```

### 4) Launch the dashboard

You have **two** minimal dashboards:

**A) Streamlit dashboard (fastest to use):**

```bash
moondev-clawdbot ui
```

**B) "No framework" dashboard (mirrors the video: `server.js` + `dashboard/index.html`):**

```bash
# make sure you have some data first
moondev-clawdbot run once --sources tiktok,x_mock

# then start the node server
node server.js
# open http://localhost:3456
```

## CLI

```bash
moondev-clawdbot --help
moondev-clawdbot sources list

# one cycle
moondev-clawdbot run once --sources tiktok,x_mock

# or step-by-step
moondev-clawdbot ingest --sources tiktok,x_mock
moondev-clawdbot score
moondev-clawdbot alert --min-score 0.65
moondev-clawdbot export --min-score 0.65

# continuous (cron-like)
moondev-clawdbot run daemon --interval-sec 300

# dashboards
moondev-clawdbot ui
node server.js
```

## Project layout

- `src/moondev_clawdbot/` – pipeline code
- `data/` – sqlite DB (created at runtime)
- `config/` – sample source lists
- `docs/` – video transcript + extracted architecture notes

## How this maps to the video

See:
- `docs/transcript.txt`
- `docs/architecture.md`
- `docs/cron.md`
- `docs/key_excerpts.md`

## License

MIT (for the code in this folder).
