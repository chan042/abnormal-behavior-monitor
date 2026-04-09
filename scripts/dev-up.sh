#!/bin/zsh

set -euo pipefail

source "${0:A:h}/dev-lib.sh"

FASTAPI_HOST="${FASTAPI_HOST:-127.0.0.1}"
FASTAPI_PORT="${FASTAPI_PORT:-8100}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
LIVE_CAMERA_CONFIG="${LIVE_CAMERA_CONFIG:-}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/dev-up.sh [--live-camera-config PATH]

Default:
  - FastAPI (127.0.0.1:8100)
  - Frontend (127.0.0.1:3000)

Options:
  --live-camera-config PATH  Pass camera config to backend server(s)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live-camera-config)
      [[ $# -ge 2 ]] || {
        print -u2 -- "--live-camera-config requires a path"
        exit 1
      }
      LIVE_CAMERA_CONFIG="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      print -u2 -- "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

ensure_run_dir
LIVE_CAMERA_CONFIG="$(resolve_live_camera_config "$LIVE_CAMERA_CONFIG")"
BACKEND_ORIGIN="${NEXT_PUBLIC_BACKEND_ORIGIN:-http://$FASTAPI_HOST:$FASTAPI_PORT}"

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  print -u2 -- ".venv/bin/python 이 없습니다. '. .venv/bin/activate' 와 의존성 설치를 먼저 확인하세요."
  exit 1
fi

start_fastapi "$FASTAPI_HOST" "$FASTAPI_PORT" "$LIVE_CAMERA_CONFIG"
start_frontend "$FRONTEND_HOST" "$FRONTEND_PORT" "$BACKEND_ORIGIN"

print_service_status "$FASTAPI_PID_FILE" "FastAPI" "http://$FASTAPI_HOST:$FASTAPI_PORT" "$FASTAPI_LOG"
print_service_status "$FRONTEND_PID_FILE" "Frontend" "http://$FRONTEND_HOST:$FRONTEND_PORT" "$FRONTEND_LOG"
