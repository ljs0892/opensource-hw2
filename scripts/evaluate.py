"""평가 실행: 음식 인식 정확도와 칼로리 오차를 측정한다.

    # 로컬 모델 직접 호출 (튜닝용)
    PYTHONPATH=.vendor python3 scripts/evaluate.py --mode local --split tuning --preprocess crop --tta 0 --name t1

    # 배포된 API 호출 (최종 측정용)
    python3 scripts/evaluate.py --mode api --url http://127.0.0.1:8000 --split final --name after

측정 지표
- 인식: top-1 / top-3 정확도
- 칼로리(보조 정답 18개 클래스만): 정답 클래스 기준 MAE/MAPE(인식과 무관한 칼로리 표 오차),
  엔드투엔드 MAE/MAPE(예측 1위 클래스의 칼로리 vs 정답 클래스의 보조 정답)
- 지연시간: 서버 측 latency_ms(api), 함수 호출 시간(local), 요청 벽시계 시간(api)

결과는 eval/results/<name>.json 에 저장한다 (eval/ 는 Git 제외).
"""

import argparse
import io
import json
import re
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"


def load_table() -> dict:
    data = json.loads((ROOT / "data" / "calorie_table.json").read_text(encoding="utf-8"))
    out = {}
    for label, item in data["items"].items():
        m = re.search(r"약 (\d+)g", item["serving"])
        out[label] = {"kcal": item["kcal"], "serving_g": int(m.group(1)) if m else None}
    return out


def reference_kcal(ref_items: dict, label: str, table: dict):
    item = ref_items.get(label)
    if not item or not table.get(label, {}).get("serving_g"):
        return None
    return item["kcal_per_100g"] * table[label]["serving_g"] / 100


def run_local(items, preprocess, tta):
    sys.path.insert(0, str(ROOT / ".vendor")) if (ROOT / ".vendor").exists() else None
    sys.path.insert(0, str(ROOT))
    from PIL import Image

    from app.classifier import FoodClassifier
    from app.config import CONFIG, resolve

    clf = FoodClassifier(resolve(CONFIG["model"]["local_dir"]), CONFIG["model"], 3,
                         preprocess=preprocess, tta_hflip=bool(tta))
    results = []
    for it in items:
        img = Image.open(EVAL / it["file"]).convert("RGB")
        start = time.time()
        t0 = time.perf_counter()
        top = clf.predict(img)
        ms = (time.perf_counter() - t0) * 1000
        results.append({"top_k": [label for label, _ in top], "confidence": round(top[0][1], 4),
                        "latency_ms": round(ms, 1), "wall_ms": round(ms, 1),
                        "start_utc": datetime.fromtimestamp(start, timezone.utc).isoformat(timespec="milliseconds"),
                        "end_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds")})
    return results


def run_api(items, base):
    results = []
    for it in items:
        data = (EVAL / it["file"]).read_bytes()
        req = urllib.request.Request(base.rstrip("/") + "/api/predict", data=data, method="POST",
                                     headers={"Content-Type": "image/jpeg"})
        start = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read())
            wall = (time.perf_counter() - t0) * 1000
            results.append({"top_k": [c["label"] for c in body["top_k"]],
                            "confidence": body["top_k"][0]["confidence"],
                            "latency_ms": body["latency_ms"], "wall_ms": round(wall, 1),
                            "status": body["status"], "app_version": body.get("app_version")})
        except Exception as exc:  # 실패도 기록한다
            wall = (time.perf_counter() - t0) * 1000
            results.append({"top_k": [], "confidence": None, "latency_ms": None, "wall_ms": round(wall, 1),
                            "error": str(exc)})
        results[-1]["start_utc"] = start.isoformat(timespec="milliseconds")
        results[-1]["end_utc"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return results


def summarize(items, results, table, ref_items):
    n = len(items)
    top1 = sum(1 for it, r in zip(items, results) if r["top_k"] and r["top_k"][0] == it["label"])
    top3 = sum(1 for it, r in zip(items, results) if it["label"] in r["top_k"][:3])
    errors = sum(1 for r in results if r.get("error"))
    lat = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]
    wall = [r["wall_ms"] for r in results]

    gold_err, e2e_err, gold_pct, e2e_pct = [], [], [], []
    for it, r in zip(items, results):
        ref = reference_kcal(ref_items, it["label"], table)
        if ref is None:
            continue
        g = table.get(it["label"], {}).get("kcal")
        if g is not None:
            gold_err.append(abs(g - ref))
            gold_pct.append(abs(g - ref) / ref * 100)
        pred_label = r["top_k"][0] if r["top_k"] else None
        p = table.get(pred_label, {}).get("kcal") if pred_label else None
        if p is not None:
            e2e_err.append(abs(p - ref))
            e2e_pct.append(abs(p - ref) / ref * 100)

    def mean(xs):
        return round(statistics.mean(xs), 2) if xs else None

    return {
        "n": n,
        "top1_acc": round(top1 / n * 100, 1),
        "top3_acc": round(top3 / n * 100, 1),
        "request_errors": errors,
        "latency_ms_mean": mean(lat),
        "latency_ms_max": round(max(lat), 1) if lat else None,
        "wall_ms_mean": mean(wall),
        "wall_ms_max": round(max(wall), 1) if wall else None,
        "kcal_n": len(gold_err),
        "kcal_mae_correct_class": mean(gold_err),
        "kcal_mape_correct_class": mean(gold_pct),
        "kcal_mae_end_to_end": mean(e2e_err),
        "kcal_mape_end_to_end": mean(e2e_pct),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["local", "api"], required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--split", choices=["tuning", "final"], required=True)
    ap.add_argument("--preprocess", default="full", choices=["full", "crop"])
    ap.add_argument("--tta", type=int, default=0)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()

    manifest = json.loads((EVAL / "manifest.json").read_text(encoding="utf-8"))["items"]
    items = [it for it in manifest if it["split"] == args.split]
    table = load_table()
    ref_items = json.loads((EVAL / "reference_subset.json").read_text(encoding="utf-8"))["items"]

    results = run_local(items, args.preprocess, args.tta) if args.mode == "local" else run_api(items, args.url)
    for it, r in zip(items, results):
        r["id"], r["gold"] = it["id"], it["label"]
        r["correct_top1"] = bool(r["top_k"]) and r["top_k"][0] == it["label"]
    summary = summarize(items, results, table, ref_items)

    out = {
        "name": args.name, "mode": args.mode, "split": args.split,
        "preprocess": args.preprocess, "tta_hflip": bool(args.tta),
        "app_version": next((r.get("app_version") for r in results if r.get("app_version")), None),
        "summary": summary, "items": results,
    }
    (EVAL / "results").mkdir(parents=True, exist_ok=True)
    (EVAL / "results" / f"{args.name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"name": args.name, "split": args.split, **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
