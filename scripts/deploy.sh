#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

check_deps() {
  info "Installing Python dependencies..."
  pip install -q -r backend/requirements.txt gunicorn 2>/dev/null && ok "Dependencies installed" || warn "Some deps failed"
}

dev() {
  info "Starting dev server → http://localhost:8000"
  python -m backend.main
}

prod() {
  PORT="${PORT:-8000}"
  WORKERS="${WORKERS:-4}"
  info "Starting production server → 0.0.0.0:$PORT (workers=$WORKERS)"
  gunicorn --bind "0.0.0.0:$PORT" --workers "$WORKERS" --timeout 120 --access-logfile - --error-logfile - backend.wsgi:app
}

docker_build() {
  info "Building Docker image..."
  docker build -t gasoff:latest . && ok "Image built"
  info "Starting container → http://localhost:8000"
  docker run -d --name gasoff -p 8000:8000 --env-file backend/.env gasoff:latest && ok "Container started"
}

set_webhook() {
  URL="${1:?Usage: $0 webhook <https://domain.com>}"
  URL="${URL%/}/webhook"
  TOKEN=$(grep TELEGRAM_BOT_TOKEN backend/.env | head -1 | cut -d= -f2-)
  info "Setting webhook → $URL"
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/setWebhook" \
    -d "url=$URL&allowed_updates=[\"message\"]" | python3 -m json.tool
}

test_bot() {
  TOKEN=$(grep TELEGRAM_BOT_TOKEN backend/.env | head -1 | cut -d= -f2-)
  info "Bot info:"; curl -s "https://api.telegram.org/bot${TOKEN}/getMe" | python3 -m json.tool
  info "Webhook info:"; curl -s "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | python3 -m json.tool
}

case "${1:-dev}" in
  dev)      check_deps && dev ;;
  prod)     check_deps && prod ;;
  docker)   docker_build ;;
  webhook)  set_webhook "${2:-}" ;;
  test)     test_bot ;;
  *)
    echo "Usage: $0 {dev|prod|docker|webhook <url>|test}"
    echo "  dev       Dev server (Flask, hot-reload)"
    echo "  prod      Production (Gunicorn)"
    echo "  docker    Docker build & run"
    echo "  webhook   Set Telegram webhook"
    echo "  test      Test bot connection"
    ;;
esac
