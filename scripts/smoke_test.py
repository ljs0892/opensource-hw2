"""실행 중인 서버에 대한 스모크 테스트 (표준 라이브러리만 사용).

    python3 scripts/smoke_test.py http://127.0.0.1:8000

- /health 가 모델 로드 완료 상태인지 확인
- 비빔밥 사진을 보내 상위 1위가 bibimbap 이고 칼로리가 포함되는지 확인
실패하면 0이 아닌 코드로 종료한다.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "images" / "bibimbap_seoul_beef.jpg"
WAIT_SECONDS = 120


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


def post_image(url: str, data: bytes):
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "image/jpeg"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def wait_until_healthy(base: str) -> dict:
    deadline = time.monotonic() + WAIT_SECONDS
    last_error = "응답 없음"
    while time.monotonic() < deadline:
        try:
            health = get_json(f"{base}/health")
            if health.get("model_loaded"):
                return health
            last_error = f"모델 미로드: {health.get('load_error')}"
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise SystemExit(f"[실패] {WAIT_SECONDS}초 안에 정상 상태가 되지 않았습니다: {last_error}")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    health = wait_until_healthy(base)
    print(f"[통과] /health: status={health['status']} model={health['model']['model_id']}@{health['model']['revision'][:8]}")

    result = post_image(f"{base}/api/predict", FIXTURE.read_bytes())
    top = result["top_k"][0]
    if result["status"] != "ok" or top["label"] != "bibimbap":
        print(f"[실패] 예측 결과: status={result['status']} top1={top['label']} ({top['confidence']})", file=sys.stderr)
        return 1
    if not top.get("nutrition", {}).get("kcal"):
        print("[실패] 상위 1위에 칼로리 정보가 없습니다", file=sys.stderr)
        return 1
    print(f"[통과] /api/predict: top1={top['label']} confidence={top['confidence']} kcal={top['nutrition']['kcal']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
