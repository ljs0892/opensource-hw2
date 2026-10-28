#!/bin/zsh
# 음식 사진 분류·칼로리 추정 앱 실행 스크립트 (macOS Terminal/zsh)
#  - 가상환경 없이 설치된 python3를 사용한다.
#  - 패키지는 프로젝트 폴더의 .vendor/ 에 설치되어 있으며 PYTHONPATH로 불러온다.
#  - 서버는 127.0.0.1에만 바인딩한다 (외부 네트워크 노출 없음).
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .vendor/fastapi ]]; then
  echo "[오류] .vendor/ 에 패키지가 없습니다. README.md의 설치 단계를 먼저 실행하세요." >&2
  exit 1
fi

export PYTHONPATH="$PWD/.vendor${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1          # 로컬에 고정된 모델만 사용 (실행 중 네트워크 요청 없음)
export HF_HUB_DISABLE_TELEMETRY=1

PORT="${PORT:-8000}"
echo "음식 분류 앱: http://127.0.0.1:${PORT}  (종료: Ctrl+C)"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT}"
