#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export CLAWDBOT_DB_PATH="${CLAWDBOT_DB_PATH:-./data/clawdbot.sqlite}"
export PORT="${PORT:-3456}"

node server.js
