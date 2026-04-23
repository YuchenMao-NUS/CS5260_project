#!/usr/bin/env bash
set -euxo pipefail

sudo mkdir -p /ms-playwright
sudo chown -R vscode:vscode /ms-playwright

python -m pip install -r backend/requirements.txt
python -m pip install -e flights-search
python -m pip install -e backend

python -m playwright install-deps chromium
python -m playwright install chromium

python -c "import mcp, smartflight, flights_search_mcp"

npm --prefix frontend install
