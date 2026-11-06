"""평가 세트 생성: Food-101 검증 샤드에서 클래스당 1장씩 100장을 뽑고 30(튜닝)/70(최종 평가)으로 나눈다.

    PYTHONPATH=.vendor python3 scripts/build_eval_set.py --shard <validation-00000-of-00003.parquet>

- 출력: eval/images/*.jpg, eval/manifest.json  (eval/ 전체는 Git 제외)
- 라이선스: Food-101 이미지는 Foodspotting 소유이며 "scientific fair use" 범위에서만 사용한다.
  이미지는 재배포하지 않는다.
- 무작위 시드 고정(SEED). 같은 입력이면 같은 결과가 나온다.
"""

import argparse
import io
import json
import random
from pathlib import Path

import pyarrow.parquet as pq
from PIL import Image

SEED = 2026
N_IMAGES = 100
N_TUNING = 30
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "eval"


def label_names(pf: pq.ParquetFile) -> list[str]:
    meta = json.loads(pf.schema_arrow.metadata[b"huggingface"])
    return meta["info"]["features"]["label"]["names"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", required=True, action="append", help="validation parquet (여러 번 지정 가능)")
    args = ap.parse_args()

    names = None
    table: list[dict] = []
    for shard in args.shard:
        pf = pq.ParquetFile(shard)
        names = names or label_names(pf)
        table.extend(pf.read(columns=["image", "label"]).to_pylist())

    by_label: dict[int, list[int]] = {}
    for row_idx, row in enumerate(table):
        by_label.setdefault(row["label"], []).append(row_idx)

    rng = random.Random(SEED)
    classes = sorted(by_label)
    chosen_classes = sorted(rng.sample(classes, N_IMAGES))

    records = []
    for label_id in chosen_classes:
        row_idx = rng.choice(by_label[label_id])
        records.append({"row_idx": row_idx, "label": names[label_id]})

    rng.shuffle(records)
    for i, rec in enumerate(records):
        rec["split"] = "tuning" if i < N_TUNING else "final"

    (OUT / "images").mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, rec in enumerate(records):
        raw = table[rec["row_idx"]]["image"]["bytes"]
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        fname = f"{rec['split']}_{i:03d}_{rec['label']}.jpg"
        img.save(OUT / "images" / fname, quality=95)
        manifest.append({
            "id": f"{i:03d}",
            "file": f"images/{fname}",
            "label": rec["label"],
            "split": rec["split"],
            "source": f"ethz/food101 validation shard, row {rec['row_idx']}",
        })

    (OUT / "manifest.json").write_text(
        json.dumps({"seed": SEED, "n": len(manifest), "items": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tuning = sum(1 for m in manifest if m["split"] == "tuning")
    print(json.dumps({"images": len(manifest), "tuning": tuning, "final": len(manifest) - tuning}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
