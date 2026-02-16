# Cron / scheduling

The video’s implementation uses **cron jobs** (OpenClaw) to run the scans every ~5 minutes.

This repo provides two equivalent options:

## Option A: Built-in daemon loop

```bash
moondev-clawdbot run daemon --sources tiktok,x_mock --interval-sec 300
```

## Option B: System cron

Example crontab entry (runs every 5 minutes):

```cron
*/5 * * * * cd /Users/sheen/clawd/moondev_clawdbot_project && . .venv/bin/activate && moondev-clawdbot run once --sources tiktok,x_mock --min-score 0.65 --top-k 10 >> data/cron.log 2>&1
```

If you want the vanilla JS dashboard, also start:

```bash
cd /Users/sheen/clawd/moondev_clawdbot_project
node server.js
```

(Or run it under a process manager like `launchd`/`systemd`.)
