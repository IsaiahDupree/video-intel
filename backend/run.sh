#!/bin/zsh -l
# Start the video-intel service. Creates venv + installs deps on first run.
set -e
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  # py3.14 ensurepip is broken on this box; pin to 3.12
  ${PYTHON:-python3.12} -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt

PORT="${PORT:-5570}"
echo "video-intel starting on :$PORT"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
