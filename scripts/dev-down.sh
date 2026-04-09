#!/bin/zsh

set -euo pipefail

source "${0:A:h}/dev-lib.sh"

stop_service "$FRONTEND_PID_FILE" "Frontend"
stop_service "$FASTAPI_PID_FILE" "FastAPI"
