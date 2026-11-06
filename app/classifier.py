"""사전 학습 음식 분류 모델 래퍼. CPU에서 추론하며, 요청 간 추론은 락으로 직렬화한다.

전처리 옵션 (설정 inference.preprocess, inference.tta_hflip):
- preprocess "full" : 기존 동작. 이미지를 224x224로 바로 리사이즈 (기본값)
- preprocess "crop": 짧은 변을 224로 맞춘 뒤 중앙 224x224를 자른다 (가로세로 비율 유지)
- tta_hflip true   : 원본과 좌우 반전 이미지의 softmax 확률을 평균한다
"""

import threading
from datetime import datetime, timezone
from pathlib import Path

import torch
from PIL import Image, ImageOps
from transformers import AutoImageProcessor, AutoModelForImageClassification

CROP_SIZE = 224


class FoodClassifier:
    def __init__(self, model_dir: Path, model_info: dict, top_k: int, preprocess: str = "full", tta_hflip: bool = False):
        if preprocess not in {"full", "crop"}:
            raise ValueError(f"알 수 없는 preprocess: {preprocess}")
        self.model_info = model_info
        self.top_k = top_k
        self.preprocess = preprocess
        self.tta_hflip = tta_hflip
        self.processor = AutoImageProcessor.from_pretrained(model_dir)
        self.model = AutoModelForImageClassification.from_pretrained(model_dir).eval()
        self.id2label = {int(k): v for k, v in self.model.config.id2label.items()}
        self.loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._lock = threading.Lock()

    @property
    def labels(self) -> list[str]:
        return list(self.id2label.values())

    def _prepare(self, image: Image.Image) -> Image.Image:
        if self.preprocess == "full":
            return image
        w, h = image.size
        scale = CROP_SIZE / min(w, h)
        image = image.resize((max(CROP_SIZE, round(w * scale)), max(CROP_SIZE, round(h * scale))), Image.BICUBIC)
        w, h = image.size
        left, top = (w - CROP_SIZE) // 2, (h - CROP_SIZE) // 2
        return image.crop((left, top, left + CROP_SIZE, top + CROP_SIZE))

    def probabilities(self, image: Image.Image) -> torch.Tensor:
        """전체 클래스의 softmax 확률 (1차원 텐서)."""
        prepared = self._prepare(image)
        views = [prepared, ImageOps.mirror(prepared)] if self.tta_hflip else [prepared]
        with self._lock, torch.inference_mode():
            inputs = self.processor(images=views, return_tensors="pt")
            logits = self.model(**inputs).logits
        return logits.softmax(dim=-1).mean(dim=0)

    def predict(self, image: Image.Image) -> list[tuple[str, float]]:
        """상위 top_k개 (라벨, 신뢰도)를 신뢰도 내림차순으로 반환한다."""
        probs = self.probabilities(image)
        values, indices = probs.topk(self.top_k)
        return [(self.id2label[int(i)], float(v)) for v, i in zip(values, indices)]
