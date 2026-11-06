"""평가 결과 요약을 docs/evaluation_summary.json 으로 만든다 (이미지·원본 결과는 포함하지 않는다).

    python3 scripts/make_eval_summary.py

입력: eval/results/*.json, eval/manifest.json, eval/reference_subset.json, data/calorie_table.json
출력: docs/evaluation_summary.json  (CD 요약 리포트가 읽는다)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate import load_table, reference_kcal  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
RESULTS = EVAL / "results"
OUT = ROOT / "docs" / "evaluation_summary.json"
MAIN_KEYS = ["before_tuning", "before_final", "after_tuning", "after_final"]
VARIANTS = {"t_full": "기준 (full, TTA 없음)", "t_crop": "중앙 크롭", "t_flip": "좌우 반전 TTA (채택)", "t_crop_flip": "중앙 크롭 + 좌우 반전 TTA"}


def load(name: str):
    path = RESULTS / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> int:
    manifest = json.loads((EVAL / "manifest.json").read_text(encoding="utf-8"))
    ref_items = json.loads((EVAL / "reference_subset.json").read_text(encoding="utf-8"))["items"]
    table = load_table()
    names = json.loads((ROOT / "data" / "calorie_table.json").read_text(encoding="utf-8"))["items"]

    summary = {}
    for key in MAIN_KEYS:
        res = load(key)
        if res:
            summary[key] = res["summary"]

    variants = {}
    for key, label in VARIANTS.items():
        res = load(key)
        if res:
            s = res["summary"]
            variants[key] = {"label": label, "top1_acc": s["top1_acc"], "top3_acc": s["top3_acc"],
                             "latency_ms_mean": s["latency_ms_mean"]}

    # 최종 세트 음식별 표 (보조 정답 클래스만). 'after'가 있으면 after 기준, 없으면 before 기준.
    final_src = load("after_final") or load("before_final")
    before = load("before_final")
    per_food = []
    if final_src:
        for item, res in zip([i for i in manifest["items"] if i["split"] == "final"], final_src["items"]):
            ref = reference_kcal(ref_items, item["label"], table)
            if ref is None:
                continue
            pred = res["top_k"][0] if res["top_k"] else None
            pred_kcal = table.get(pred, {}).get("kcal") if pred else None
            row = {
                "name_ko": names[item["label"]]["name_ko"],
                "gold": item["label"],
                "pred": pred,
                "pred_kcal": pred_kcal,
                "ref_kcal": round(ref, 1),
                "correct": pred == item["label"],
            }
            if before:
                bp = next((b for b in before["items"] if b["id"] == item["id"]), None)
                row["pred_before"] = bp["top_k"][0] if bp and bp["top_k"] else None
            per_food.append(row)

    out = {
        "dataset": {
            "images": len(manifest["items"]),
            "tuning": sum(1 for i in manifest["items"] if i["split"] == "tuning"),
            "final": sum(1 for i in manifest["items"] if i["split"] == "final"),
            "seed": manifest["seed"],
            "source": "ethz/food101 validation split (Foodspotting 이미지, scientific fair use)",
            "images_in_git": False,
        },
        "calorie_reference": {
            "type": "proxy",
            "description": "USDA SR Legacy 기반 보조 정답 18개 클래스 (사진별 실측 아님, 표본 작음)",
            "classes": len(ref_items),
        },
        "changes": {
            "attempt_1_preprocess": "좌우 반전 TTA 추가 (inference.tta_hflip: false → true), 전처리 크기 방식은 유지",
            "attempt_2_calorie": "미적용 (칼로리 정답 부재로 변경 효과 검증 불가)",
            "attempts_used": 1,
        },
        "summary": summary,
        "variants_tuning": variants,
        "per_food_final": per_food,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "keys": sorted(summary), "per_food": len(per_food)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
