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

### 2b) (Optional) Use the Playwright TikTok collector (real links)

By default, the `tiktok` source uses seed/mock data unless you set:

```bash
export TIKTOK_COLLECTOR=playwright
```

Run these from the **repo root** (or set `CLAWDBOT_DB_PATH` to an absolute path) so the CLI and `node server.js` read/write the **same SQLite file**:

```bash
# one-time setup
pip install playwright
playwright install chromium

# first run headful so you can log in and persist cookies
export TIKTOK_COLLECTOR=playwright
export TIKTOK_HEADLESS=0
moondev-clawdbot ingest --sources tiktok
```

If the dashboard still shows `https://www.tiktok.com/@example/video/...`, you likely have old mock rows in the DB (see cleanup below).

#### Screenshot capture (Playwright collector, always-on)

When using the Playwright TikTok collector, the ingest step **always** captures screenshots per video (default: 5 frames, every 3 seconds). You can tune capture settings:

```bash
export TIKTOK_COLLECTOR=playwright
export TIKTOK_SCREENSHOT_COUNT=5
export TIKTOK_SCREENSHOT_INTERVAL_SEC=3

# keep it small while testing
export TIKTOK_SCAN_VIDEOS=1

moondev-clawdbot ingest --sources tiktok
```

Screenshots are saved under:

- `data/screenshots/<item_id>/frame_01.png`, `frame_02.png`, ...

### 2c) Cleanup: remove placeholder `@example` rows (optional)

Dry-run (prints matches, no deletes):

```bash
python3 scripts/cleanup_example_rows.py --db ./data/clawdbot.sqlite
```

Apply (actually deletes):

```bash
python3 scripts/cleanup_example_rows.py --db ./data/clawdbot.sqlite --apply
```

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

If an item has screenshots in `metrics_json.screenshots`, the table will show a **view** link and you can click the row to open a side panel with the screenshot frames.

## Vision-first enrichment (batch)

During ingest, items are enriched with a lightweight offline regex approach by default.

For **vision-first** enrichment using the captured TikTok screenshots, run the batch command (credential-free by default):

```bash
moondev-clawdbot enrich-vision --limit 50 --provider stub
```

This writes structured output into `metrics_json.llm_enrich`, including:
- `main_trend` / `context`
- `entities`
- `candidates` (stocks/crypto/events with confidence) + `asset_type`
- `why_spreading`
- `risk_flags`

### Optional: real VLM via OpenAI

The default provider is a deterministic offline stub so the repo runs without credentials.

If you want real vision-model output, install the OpenAI SDK and set a key:

```bash
pip install openai
export OPENAI_API_KEY=...
export VISION_ENRICH_MODEL=gpt-4o-mini

moondev-clawdbot enrich-vision --provider openai --limit 50
```

(You can also run `--provider codex` as a placeholder hook for an internal runner; this repo will fall back to stub output.)

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
