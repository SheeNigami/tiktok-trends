# Data schema

This project uses a normalized `Item` schema (see `src/moondev_clawdbot/models.py`).

Each ingested record becomes:

- `item_id`: stable hash (source + url/title)
- `source`: `tiktok|x_mock|hn|rss|reddit|...`
- `url`, `title`, `text`
- `metrics` (stored as JSON): source-specific metrics and extracted signals
  - Engagement: `views`, `likes`, `comments`, `shares`, `points`, …
  - TikTok-specific: `view_velocity` (0..1 or views/unit-time)
  - Keyword rotation: `keyword`
  - Extracted: `brands`, `tickers`
  - Investable mapping: `investable: [{brand,status,ticker,parent,notes}, ...]`
- `score`: 0..1 "confidence" score (see `src/moondev_clawdbot/score.py`)
- `score_breakdown`: JSON weights + sub-scores
- `created_at`, `fetched_at`

SQLite tables are created automatically in `data/clawdbot.sqlite`.
