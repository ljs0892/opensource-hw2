"""모델이 실제로 로드되고 추론하는지 확인한다. 실패하면 0이 아닌 코드로 종료한다.

Docker 빌드의 모델 단계에서 실행되어, 모델이 깨졌다면 이미지가 만들어지지 않게 한다.

    PYTHONPATH=.vendor python3 scripts/verify_model.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image  # noqa: E402

from app.classifier import FoodClassifier  # noqa: E402
from app.config import CONFIG, resolve  # noqa: E402

EXPECTED_LABEL = "bibimbap"
EXPECTED_NUM_LABELS = 101
MIN_CONFIDENCE = 0.9
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "images" / "bibimbap_seoul_beef.jpg"


def fail(message: str) -> int:
    print(f"[검증 실패] {message}", file=sys.stderr)
    return 1


def main() -> int:
    model = CONFIG["model"]
    model_dir = resolve(model["local_dir"])
    if not (model_dir / model["weights_file"]).is_file():
        return fail(f"가중치 파일이 없습니다: {model_dir}")

    classifier = FoodClassifier(model_dir, model, top_k=CONFIG["inference"]["top_k"])
    if len(classifier.labels) != EXPECTED_NUM_LABELS:
        return fail(f"라벨 수가 {len(classifier.labels)}개입니다 (기대 {EXPECTED_NUM_LABELS}개)")

    image = Image.open(FIXTURE).convert("RGB")
    top = classifier.predict(image)
    label, confidence = top[0]
    if label != EXPECTED_LABEL or confidence < MIN_CONFIDENCE:
        return fail(f"예측이 기대와 다릅니다: top1={label} ({confidence:.4f})")

    print(json.dumps({
        "model_loaded": True,
        "model_id": model["model_id"],
        "revision": model["revision"],
        "num_labels": len(classifier.labels),
        "fixture_top1": label,
        "fixture_confidence": round(confidence, 4),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
