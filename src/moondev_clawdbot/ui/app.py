from __future__ import annotations

import os
import subprocess
from pathlib import Path


def run_streamlit(db_path: str, port: int = 8501) -> None:
    """Launch streamlit dashboard.

    We pass DB path via env var to keep the dashboard script simple.
    """
    dash = Path(__file__).with_name("dashboard.py")
    env = os.environ.copy()
    env["CLAWDBOT_DB_PATH"] = db_path
    cmd = [
        "streamlit",
        "run",
        str(dash),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    ]
    subprocess.run(cmd, check=True, env=env)
