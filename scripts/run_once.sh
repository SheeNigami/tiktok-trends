#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate 2>/dev/null || true

moondev-clawdbot run once --sources "${1:-tiktok,x_mock}" --min-score "${2:-0.65}" --top-k "${3:-10}" --channel "${4:-auto}"
