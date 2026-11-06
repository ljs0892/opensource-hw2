#!/usr/bin/env bash
# 무중단 배포: 블루/그린 두 앱 컨테이너 + nginx 라우터 (macOS, Docker Desktop)
#
#   IMAGE=ljs0892/food-calorie-app:sha-<커밋> PHASE_LOG=monitor/phases.log scripts/deploy_bluegreen.sh
#
# 구조
#   - food-router (nginx) 가 127.0.0.1:8000 을 항상 점유 → 접속 주소 유지
#   - 유휴 색(blue/green)에 새 이미지를 띄우고, 컨테이너 안에서 스모크 테스트 통과 시에만 전환
#   - 전환은 nginx upstream 교체 + graceful reload (진행 중 요청은 끝까지 처리)
#   - 검증 실패 시 라우터는 건드리지 않고 새 컨테이너만 제거 → 서비스 중단 없음
#   - 최초 1회는 무중단 구성 이전의 단일 컨테이너(food-calorie-app)를 내리므로 짧은 공백이 생긴다
set -euo pipefail

export PATH="$HOME/.docker/bin:/usr/local/bin:$PATH"

IMAGE="${IMAGE:?IMAGE 환경 변수가 필요합니다 (예: ljs0892/food-calorie-app:sha-5acfbe1)}"
PORT="${HOST_PORT:-8000}"
DATA_DIR="${DATA_DIR:-$HOME/food-calorie-app-data}"
PHASE_LOG="${PHASE_LOG:-}"
NET="food-net"
ROUTER="food-router"
ROUTER_IMAGE="nginx:1.27-alpine"
LEGACY="food-calorie-app"
STATE="$DATA_DIR/router"
BASE_URL="http://127.0.0.1:${PORT}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

log() { printf '[deploy] %s\n' "$*"; }
fail() { printf '[deploy][오류] %s\n' "$*" >&2; }
phase() {
  log "PHASE $1 $2"
  if [ -n "$PHASE_LOG" ]; then
    printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" >> "$PHASE_LOG"
  fi
}
running() { docker ps --format '{{.Names}}' | grep -qx "$1"; }
exists() { docker ps -a --format '{{.Names}}' | grep -qx "$1"; }
other() { if [ "$1" = blue ]; then echo green; else echo blue; fi; }

write_router_conf() {
  mkdir -p "$STATE"
  cat > "$STATE/default.conf.tmp" <<EOF
upstream food_backend {
    server food-app-$1:8000;
}
server {
    listen 80;
    client_max_body_size 11m;
    location / {
        proxy_pass http://food_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_connect_timeout 2s;
        proxy_read_timeout 120s;
        proxy_next_upstream error timeout http_502 http_503 http_504;
    }
}
EOF
  mv "$STATE/default.conf.tmp" "$STATE/default.conf"
}

reload_router() {
  docker exec "$ROUTER" nginx -t >/dev/null
  docker exec "$ROUTER" nginx -s reload >/dev/null
}

start_app() { # $1 = color
  docker run -d \
    --name "food-app-$1" \
    --network "$NET" \
    --restart unless-stopped \
    -v "$DATA_DIR/logs:/app/logs" \
    "$IMAGE" >/dev/null
}

internal_smoke() { # 컨테이너 내부에서 스모크 테스트 (외부 포트 게시 없이 검증)
  docker exec "food-app-$1" python3 scripts/smoke_test.py http://127.0.0.1:8000
}

docker info >/dev/null 2>&1 || { fail "Docker 데몬에 연결할 수 없습니다. Docker Desktop을 실행하세요."; exit 1; }
docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
mkdir -p "$DATA_DIR/logs"

phase DEPLOY_START "image=$IMAGE"
if [ "${SKIP_PULL:-0}" = "1" ]; then
  log "SKIP_PULL=1: 로컬 이미지 사용 ($IMAGE)"
  docker image inspect "$IMAGE" >/dev/null
else
  log "이미지 받기: $IMAGE"
  docker pull "$IMAGE" >/dev/null
fi

active=""
if [ -f "$STATE/active" ] && running "$ROUTER"; then
  active="$(cat "$STATE/active")"
fi

if [ -z "$active" ]; then
  # ---- 최초 설치 (또는 라우터 없음) ----
  # 새 컨테이너를 먼저 검증한다. 검증 전에는 기존 서비스를 건드리지 않는다.
  color="blue"
  log "최초 설치: $color 시작 (기존 단일 컨테이너는 검증 통과 후에만 내린다)"
  exists "food-app-$color" && docker rm -f "food-app-$color" >/dev/null
  start_app "$color"
  internal_smoke "$color" || { fail "초기 컨테이너 검증 실패. 기존 서비스는 그대로 유지됩니다."; docker logs --tail 80 "food-app-$color" >&2 || true; docker rm -f "food-app-$color" >/dev/null || true; exit 1; }
  phase IDLE_READY "color=$color (최초)"
  if exists "$LEGACY"; then
    # 포트 8000을 라우터가 가져가야 하므로 기존 단일 컨테이너를 내린다 (1회성 공백 구간)
    phase MIGRATE_STOP_LEGACY "기존 단일 컨테이너 중지 (1회성 전환 공백 발생 구간)"
    docker rm -f "$LEGACY" >/dev/null
  fi
  write_router_conf "$color"
  exists "$ROUTER" && docker rm -f "$ROUTER" >/dev/null
  docker run -d --name "$ROUTER" --network "$NET" --restart unless-stopped \
    -p "127.0.0.1:${PORT}:80" \
    -v "$STATE:/etc/nginx/conf.d:ro" \
    "$ROUTER_IMAGE" >/dev/null
  sleep 2
  python3 "$ROOT/scripts/smoke_test.py" "$BASE_URL"
  echo "$color" > "$STATE/active"
  phase SWITCH_DONE "color=$color (최초 전환)"
  log "최초 배포 완료: $color"
  exit 0
fi

# ---- 무중단 전환 ----
idle="$(other "$active")"
log "현재 활성: $active / 새 버전을 올릴 유휴 색: $idle"
exists "food-app-$idle" && docker rm -f "food-app-$idle" >/dev/null
start_app "$idle"
if ! internal_smoke "$idle"; then
  fail "새 컨테이너(food-app-$idle) 검증 실패. 라우터는 건드리지 않았으므로 서비스는 $active 가 계속 처리합니다."
  docker logs --tail 80 "food-app-$idle" >&2 || true
  docker rm -f "food-app-$idle" >/dev/null || true
  exit 1
fi
phase IDLE_READY "color=$idle"

write_router_conf "$idle"
if ! reload_router; then
  fail "라우터 설정 검증 실패, 이전 설정으로 되돌립니다."
  write_router_conf "$active"; reload_router || true
  docker rm -f "food-app-$idle" >/dev/null || true
  exit 1
fi
phase SWITCH_DONE "from=$active to=$idle"

if ! python3 "$ROOT/scripts/smoke_test.py" "$BASE_URL"; then
  fail "전환 후 외부 경로 검증 실패, $active 로 복구합니다."
  write_router_conf "$active"; reload_router || true
  phase ROLLBACK "to=$active"
  docker rm -f "food-app-$idle" >/dev/null || true
  exit 1
fi
echo "$idle" > "$STATE/active"

if exists "food-app-$active"; then
  docker stop -t 20 "food-app-$active" >/dev/null || true
  phase OLD_STOPPED "color=$active (롤백용으로 중지만 함, 다음 배포에서 제거)"
fi
phase DEPLOY_DONE "active=$idle"
log "배포 완료: 활성 색 $idle, 접속 주소 $BASE_URL"
