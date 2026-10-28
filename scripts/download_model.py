"""config/model.json에 고정된 모델 리비전을 local_dir로 내려받는다.

실행 (프로젝트 루트에서):
    PYTHONPATH=.vendor python3 scripts/download_model.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import CONFIG, resolve  # noqa: E402


def main() -> int:
    from huggingface_hub import snapshot_download

    model = CONFIG["model"]
    target = resolve(model["local_dir"])
    print(f"모델: {model['model_id']} @ {model['revision']}")
    print(f"저장 위치: {target}")
    path = snapshot_download(
        repo_id=model["model_id"],
        revision=model["revision"],
        local_dir=target,
        allow_patterns=["*.json", "*.bin", "*.md"],
    )
    print(json.dumps({"downloaded_to": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
