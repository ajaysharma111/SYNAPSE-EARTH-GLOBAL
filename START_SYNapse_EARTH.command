#!/bin/zsh
set -e
cd "$(dirname "$0")"
echo "SYNAPSE EARTH — starting local server"
if [ ! -d .venv ]; then
  echo "Creating Python environment…"
  python3 -m venv .venv
fi
source .venv/bin/activate
python3 -m pip install -r requirements.txt
mkdir -p data regions downloads
if [ ! -s data/world_countries.geojson ]; then
  echo "Installing world country overview…"
  python3 scripts/download_world_map.py
fi
echo "Opening http://127.0.0.1:8080"
open "http://127.0.0.1:8080" || true
python3 -m synapse.server --data ./data --host 127.0.0.1 --port 8080
