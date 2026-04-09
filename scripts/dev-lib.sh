#!/bin/zsh

unsetopt BG_NICE 2>/dev/null || true

LIB_FILE=${(%):-%N}
SCRIPT_DIR=${LIB_FILE:A:h}
ROOT_DIR=${SCRIPT_DIR:h}
RUN_DIR="$ROOT_DIR/.run"

FASTAPI_PID_FILE="$RUN_DIR/fastapi.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

FASTAPI_LOG="/tmp/abnormal-monitor-fastapi.log"
FRONTEND_LOG="/tmp/abnormal-monitor-frontend.log"

ensure_run_dir() {
  mkdir -p "$RUN_DIR"
}

read_pid_file() {
  local pid_file="$1"

  if [[ -f "$pid_file" ]]; then
    tr -d '[:space:]' < "$pid_file"
  fi
}

pid_is_running() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

managed_pid() {
  local pid_file="$1"
  local pid

  pid="$(read_pid_file "$pid_file")"
  if pid_is_running "$pid"; then
    print -- "$pid"
    return 0
  fi

  rm -f "$pid_file"
  return 1
}

port_listener_pid() {
  local port="$1"

  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi

  {
    lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
  } | head -n 1
}

ensure_node_runtime() {
  if command -v node >/dev/null 2>&1; then
    return 0
  fi

  if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    source "$HOME/.nvm/nvm.sh"
    (
      cd "$ROOT_DIR/frontend" >/dev/null 2>&1 || exit 1
      nvm use >/dev/null 2>&1
    ) || true
  fi

  if ! command -v node >/dev/null 2>&1; then
    print -u2 -- "node 명령을 찾지 못했습니다. 'cd frontend && nvm use' 후 다시 실행하세요."
    return 1
  fi
}

resolve_live_camera_config() {
  local config_path="${1:-}"

  if [[ -z "$config_path" ]]; then
    return 0
  fi

  if [[ "$config_path" != /* ]]; then
    config_path="$ROOT_DIR/$config_path"
  fi

  if [[ ! -f "$config_path" ]]; then
    print -u2 -- "카메라 설정 파일이 없습니다: $config_path"
    return 1
  fi

  print -- "$config_path"
}

start_fastapi() {
  local host="$1"
  local port="$2"
  local live_camera_config="${3:-}"
  local existing_pid
  local listener_pid
  local -a cmd

  existing_pid="$(managed_pid "$FASTAPI_PID_FILE" || true)"
  if [[ -n "$existing_pid" ]]; then
    print -- "FastAPI already running: pid=$existing_pid url=http://$host:$port"
    return 0
  fi

  listener_pid="$(port_listener_pid "$port")"
  if [[ -n "$listener_pid" ]]; then
    print -u2 -- "FastAPI 포트 $port 가 이미 사용 중입니다: pid=$listener_pid"
    return 1
  fi

  cmd=(
    "$ROOT_DIR/.venv/bin/python"
    -m
    backend.app.main
    serve-fastapi
    --host
    "$host"
    --port
    "$port"
  )

  if [[ -n "$live_camera_config" ]]; then
    cmd+=(--live-camera-config "$live_camera_config")
  fi

  nohup "${cmd[@]}" > "$FASTAPI_LOG" 2>&1 &
  print -- "$!" >| "$FASTAPI_PID_FILE"

  sleep 1
  existing_pid="$(managed_pid "$FASTAPI_PID_FILE" || true)"
  if [[ -z "$existing_pid" ]]; then
    print -u2 -- "FastAPI 시작 실패. 로그 확인: $FASTAPI_LOG"
    return 1
  fi

  print -- "FastAPI started: pid=$existing_pid url=http://$host:$port"
}

start_frontend() {
  local host="$1"
  local port="$2"
  local backend_origin="$3"
  local existing_pid
  local listener_pid

  existing_pid="$(managed_pid "$FRONTEND_PID_FILE" || true)"
  if [[ -n "$existing_pid" ]]; then
    print -- "Frontend already running: pid=$existing_pid url=http://$host:$port"
    return 0
  fi

  listener_pid="$(port_listener_pid "$port")"
  if [[ -n "$listener_pid" ]]; then
    print -u2 -- "Frontend 포트 $port 가 이미 사용 중입니다: pid=$listener_pid"
    return 1
  fi

  ensure_node_runtime || return 1

  if [[ ! -x "$ROOT_DIR/frontend/node_modules/.bin/next" ]]; then
    print -u2 -- "frontend/node_modules 가 없습니다. 'cd frontend && npm install' 후 다시 실행하세요."
    return 1
  fi

  (
    cd "$ROOT_DIR/frontend" || exit 1
    export NEXT_PUBLIC_BACKEND_ORIGIN="$backend_origin"
    nohup ./node_modules/.bin/next dev --webpack --hostname "$host" --port "$port" > "$FRONTEND_LOG" 2>&1 &
    print -- "$!" >| "$FRONTEND_PID_FILE"
  )

  sleep 1
  existing_pid="$(managed_pid "$FRONTEND_PID_FILE" || true)"
  if [[ -z "$existing_pid" ]]; then
    print -u2 -- "Frontend 시작 실패. 로그 확인: $FRONTEND_LOG"
    return 1
  fi

  print -- "Frontend started: pid=$existing_pid url=http://$host:$port"
}

stop_service() {
  local pid_file="$1"
  local label="$2"
  local pid
  local attempt

  pid="$(managed_pid "$pid_file" || true)"
  if [[ -z "$pid" ]]; then
    print -- "$label already stopped"
    return 0
  fi

  kill "$pid" 2>/dev/null || true
  for attempt in {1..20}; do
    if ! pid_is_running "$pid"; then
      rm -f "$pid_file"
      print -- "$label stopped"
      return 0
    fi
    sleep 0.25
  done

  kill -9 "$pid" 2>/dev/null || true
  sleep 0.25

  if pid_is_running "$pid"; then
    print -u2 -- "$label 종료 실패: pid=$pid"
    return 1
  fi

  rm -f "$pid_file"
  print -- "$label stopped"
}

print_service_status() {
  local pid_file="$1"
  local label="$2"
  local url="$3"
  local log_path="$4"
  local pid

  pid="$(managed_pid "$pid_file" || true)"
  if [[ -n "$pid" ]]; then
    print -- "$label: running pid=$pid url=$url log=$log_path"
  else
    print -- "$label: stopped"
  fi
}
