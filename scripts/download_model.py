"""config/model.json에 고정된 모델 리비전을 local_dir로 내려받고 가중치 무결성을 확인한다.

실행 (프로젝트 루트에서):
    PYTHONPATH=.vendor python3 scripts/download_model.py

Docker 빌드에서도 같은 스크립트를 사용한다.
"""

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import CONFIG, resolve  # noqa: E402


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    from huggingface_hub import snapshot_download

    model = CONFIG["model"]
    target = resolve(model["local_dir"])
    print(f"모델: {model['model_id']} @ {model['revision']}")
    print(f"저장 위치: {target}")
    path = Path(
        snapshot_download(
            repo_id=model["model_id"],
            revision=model["revision"],
            local_dir=target,
            allow_patterns=["*.json", "*.bin", "*.md"],
        )
    )

    weights = path / model["weights_file"]
    expected = model["weights_sha256"]
    actual = sha256_of(weights)
    if actual != expected:
        print(f"[오류] 가중치 해시 불일치: {weights.name}\n  기대값 {expected}\n  실제값 {actual}", file=sys.stderr)
        return 1
    print(json.dumps({"downloaded_to": str(path), "weights_sha256_ok": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
