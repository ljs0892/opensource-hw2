"""JSON Lines(한 줄에 JSON 한 개) 로그 writer. 이미지 데이터는 기록하지 않는다."""

import json
import threading
from pathlib import Path


class JsonlLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
