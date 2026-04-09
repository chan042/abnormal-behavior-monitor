#!/bin/zsh

set -euo pipefail

source "${0:A:h}/dev-lib.sh"

FASTAPI_HOST="${FASTAPI_HOST:-127.0.0.1}"
FASTAPI_PORT="${FASTAPI_PORT:-8100}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

print_service_status "$FASTAPI_PID_FILE" "FastAPI" "http://$FASTAPI_HOST:$FASTAPI_PORT" "$FASTAPI_LOG"
print_service_status "$FRONTEND_PID_FILE" "Frontend" "http://$FRONTEND_HOST:$FRONTEND_PORT" "$FRONTEND_LOG"
