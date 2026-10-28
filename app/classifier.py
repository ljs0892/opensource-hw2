"""사전 학습 음식 분류 모델 래퍼. CPU에서 추론하며, 요청 간 추론은 락으로 직렬화한다."""

import threading
from datetime import datetime, timezone
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForImageClassification


class FoodClassifier:
    def __init__(self, model_dir: Path, model_info: dict, top_k: int):
        self.model_info = model_info
        self.top_k = top_k
        self.processor = AutoImageProcessor.from_pretrained(model_dir)
        self.model = AutoModelForImageClassification.from_pretrained(model_dir).eval()
        self.id2label = {int(k): v for k, v in self.model.config.id2label.items()}
        self.loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._lock = threading.Lock()

    @property
    def labels(self) -> list[str]:
        return list(self.id2label.values())

    def predict(self, image: Image.Image) -> list[tuple[str, float]]:
        """상위 top_k개 (라벨, 신뢰도)를 신뢰도 내림차순으로 반환한다."""
        with self._lock, torch.inference_mode():
            inputs = self.processor(images=image, return_tensors="pt")
            logits = self.model(**inputs).logits
        probs = logits.softmax(dim=-1)[0]
        values, indices = probs.topk(self.top_k)
        return [(self.id2label[int(i)], float(v)) for v, i in zip(values, indices)]
