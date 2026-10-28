"""설정 로더. config/model.json을 읽고, 상대 경로는 프로젝트 루트 기준으로 해석한다.

모델 ID·리비전·임계값 등은 코드가 아니라 설정 파일에서만 바꾼다.
다른 설정 파일을 쓰려면 환경 변수 FOOD_APP_CONFIG에 경로를 지정한다.
"""

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "model.json"


def load_config(path: str | os.PathLike | None = None) -> dict:
    config_path = Path(path or os.environ.get("FOOD_APP_CONFIG") or DEFAULT_CONFIG_PATH)
    with config_path.open(encoding="utf-8") as f:
        return json.load(f)


def resolve(relative_path: str) -> Path:
    return PROJECT_ROOT / relative_path


CONFIG = load_config()
