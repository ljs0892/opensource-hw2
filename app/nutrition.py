"""음식 종류별 1인분 기준 칼로리 대략값 테이블."""

import json
from pathlib import Path


class CalorieTable:
    def __init__(self, path: Path):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.unit: str = data["unit"]
        self.notice: str = data["notice"]
        self._items: dict[str, dict] = data["items"]

    def name_ko(self, label: str) -> str:
        item = self._items.get(label)
        return item["name_ko"] if item else label

    def lookup(self, label: str) -> dict | None:
        item = self._items.get(label)
        if item is None:
            return None
        return {"serving": item["serving"], "kcal": item["kcal"], "unit": self.unit}

    def all_rows(self) -> list[dict]:
        return [
            {"label": label, "name_ko": item["name_ko"], "serving": item["serving"], "kcal": item["kcal"]}
            for label, item in self._items.items()
        ]

    def has_label(self, label: str) -> bool:
        return label in self._items

    def missing_labels(self, labels: list[str]) -> list[str]:
        return sorted(set(labels) - set(self._items))
