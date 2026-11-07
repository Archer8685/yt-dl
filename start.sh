#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
[ -x .venv/bin/python ] || "$PY" -m venv .venv
echo "安裝 / 更新套件（含最新版 yt-dlp）..."
.venv/bin/python -m pip install -q -U --disable-pip-version-check -r requirements.txt
( sleep 2; (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8765) || (command -v open >/dev/null && open http://127.0.0.1:8765) || true ) &
exec .venv/bin/python server.py
