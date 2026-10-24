#!/usr/bin/env bash
# Foreground local server. Ctrl+C stops the process.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo 'Create .venv and install requirements.txt first (see README).'
  exit 1
fi
PORT="$("$PY" - <<'PY'
from app.config import load_config
import socket
cfg=load_config()
with socket.socket() as sock:
    try:
        sock.bind((cfg.host,cfg.port))
        print(cfg.port)
    except OSError:
        raise SystemExit('Port unavailable; stop the other process or edit config.yaml.')
PY
)"
echo "ResearchDock: http://127.0.0.1:${PORT} (Ctrl+C to stop)"
exec "$PY" -m uvicorn app.web.app:app --host 127.0.0.1 --port "$PORT" --log-level info
