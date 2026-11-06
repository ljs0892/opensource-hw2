"""모니터링 결과 요약 (GitHub Actions Summary 용 Markdown 생성).

    python3 scripts/monitor_report.py --dir monitor --eval docs/evaluation_summary.json \
        --service-url http://127.0.0.1:8000 --md monitor/summary.md

관측 범위 밖의 구간은 "미검증"으로 표시하고, 무중단 여부는 관측된 요청 구간 안에서만 판단한다.
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

SAMPLE_GAP_LIMIT_S = 2.5  # 요청 간격이 이보다 길면 관측 공백으로 본다
POST_DEPLOY_WINDOW_S = 30


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def read_phases(path: Path) -> list[tuple[datetime, str, str]]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        parts = ln.split(maxsplit=2)
        if len(parts) >= 2:
            out.append((parse(parts[0]), parts[1], parts[2] if len(parts) > 2 else ""))
    return out


def outages(records: list[dict]) -> list[dict]:
    windows, run = [], []
    for r in records:
        if not r["success"]:
            run.append(r)
        elif run:
            windows.append(run)
            run = []
    if run:
        windows.append(run)
    out = []
    for w in windows:
        start, end = parse(w[0]["start_utc"]), parse(w[-1]["end_utc"])
        out.append({"from_seq": w[0]["seq"], "to_seq": w[-1]["seq"], "count": len(w),
                    "start": start, "end": end, "seconds": round((end - start).total_seconds(), 1)})
    return out


def sampling_gaps(records: list[dict]) -> list[tuple[datetime, datetime, float]]:
    gaps = []
    for a, b in zip(records, records[1:]):
        dt = (parse(b["start_utc"]) - parse(a["start_utc"])).total_seconds()
        if dt > SAMPLE_GAP_LIMIT_S:
            gaps.append((parse(a["end_utc"]), parse(b["start_utc"]), round(dt, 2)))
    return gaps


def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def build(args) -> str:
    d = Path(args.dir)
    recs = read_jsonl(d / "requests.jsonl")
    phases = read_phases(d / "phases.log")
    ok = [r for r in recs if r["success"]]
    fail = [r for r in recs if not r["success"]]
    wall = [r["wall_ms"] for r in ok] or [0]
    srv = [r["server_latency_ms"] for r in ok if r.get("server_latency_ms") is not None] or [0]
    versions = []
    for r in recs:
        v = r.get("app_version")
        if v and v not in versions:
            versions.append(v)
    phase_names = [p[1] for p in phases]
    deploy_done = next((p[0] for p in phases if p[1] == "DEPLOY_DONE"), None)
    deploy_start = next((p[0] for p in phases if p[1] == "DEPLOY_START"), None)
    switch = next((p[0] for p in phases if p[1] == "SWITCH_DONE"), None)
    migrate = next((p[0] for p in phases if p[1] == "MIGRATE_STOP_LEGACY"), None)

    lines = ["# 음식 분류·칼로리 서비스 배포 및 모니터링 결과", ""]
    lines += ["## 1. 서비스 접속 주소", f"- {args.service_url} (이 Mac 로컬 전용, 외부 네트워크 미공개)", ""]

    lines += ["## 2. 배포 버전", md_table(["구분", "버전"], [
        ["관측 첫 요청 버전 (배포 전)", recs[0].get("app_version") if recs else None],
        ["관측 마지막 요청 버전 (배포 후)", recs[-1].get("app_version") if recs else None],
        ["관측된 버전 목록", " → ".join(str(v) for v in versions) or None],
    ]), ""]

    lines += ["## 3. 모니터링 요청 집계 (고정 이미지 1장, 1초 간격)", md_table(["항목", "값"], [
        ["요청 수", len(recs)],
        ["성공 / 실패", f"{len(ok)} / {len(fail)}"],
        ["성공률", f"{(len(ok) / len(recs) * 100):.2f}%" if recs else "N/A"],
        ["응답 시간 평균 / 최대 (ms, 클라이언트 측)", f"{sum(wall) / len(wall):.1f} / {max(wall):.1f}"],
        ["서버 처리 시간 평균 / 최대 (ms)", f"{sum(srv) / len(srv):.1f} / {max(srv):.1f}"],
        ["관측 시작 ~ 종료", f"{recs[0]['start_utc']} ~ {recs[-1]['end_utc']}" if recs else "N/A"],
    ]), ""]

    if recs:
        lines += ["## 4. 무중단 판단 (관측 범위 내)"]
        outs = outages(recs)
        if not outs:
            lines += [f"- 관측된 {len(recs)}건 요청 구간에서 실패 0건 → **관측 범위 내 무중단**"]
        else:
            lines += [f"- 실패 구간 {len(outs)}개 관측 (무중단 아님)"]
            lines += [md_table(["실패 요청 seq", "건수", "시작", "끝", "지속(초)"], [
                [f"{o['from_seq']}~{o['to_seq']}", o["count"], o["start"].isoformat(), o["end"].isoformat(), o["seconds"]]
                for o in outs])]
        gaps = sampling_gaps(recs)
        if gaps:
            lines += [f"- 관측 공백(요청 간격 {SAMPLE_GAP_LIMIT_S}초 초과) {len(gaps)}곳 → 해당 구간은 **미검증**"]
            lines += [md_table(["공백 시작", "공백 끝", "간격(초)"], [[a.isoformat(), b.isoformat(), g] for a, b, g in gaps])]
        else:
            lines += ["- 요청 간격 이상 공백 없음 (관측 구간 전체 검증)"]
        lines += [""]

    if phases:
        lines += ["## 5. 배포 단계 타임라인", md_table(["시각 (UTC)", "단계", "내용"], [
            [t.isoformat(timespec="seconds"), name, detail] for t, name, detail in phases]), ""]
        if deploy_done:
            window_end = deploy_done + timedelta(seconds=POST_DEPLOY_WINDOW_S)
            window = [r for r in recs if deploy_done <= parse(r["start_utc"]) <= window_end]
            post_fail = [r for r in window if not r["success"]]
            lines += [f"- 배포 완료 후 {POST_DEPLOY_WINDOW_S}초 관찰: 요청 {len(window)}건, 실패 {len(post_fail)}건", ""]
        if migrate:
            lines += ["> 최초 1회 전환(단일 컨테이너 → 무중단 구성)은 포트를 넘기는 공백이 있을 수 있어, 위 실패 구간에 포함되면 이 전환에 해당한다.", ""]

    lines += ["## 6. 식별된 음식과 추정 1인분 칼로리 (고정 이미지 기준)"]
    by_label: dict[str, int] = {}
    for r in ok:
        key = f"{r['recognized_name_ko']} ({r['recognized_label']})"
        by_label[key] = by_label.get(key, 0) + 1
    last = ok[-1] if ok else None
    if last:
        lines += [f"- 인식: {last['recognized_name_ko']} ({last['recognized_label']}), 신뢰도 {last['confidence']*100:.1f}%, "
                  f"표준 1인분 {last['estimated_portion_g']}g, 예상 {last['kcal']} kcal (사진 기반 양 추정 아님)"]
    lines += [f"- 인식 결과 분포: {by_label or '없음'}", ""]

    ev = Path(args.eval) if args.eval else None
    if ev and ev.exists():
        e = json.loads(ev.read_text(encoding="utf-8"))
        lines += ["## 7. 검증 세트 평가 (음식 인식 정확도, 칼로리 오차)"]
        lines += [f"- 평가 세트: {e['dataset']['images']}장 (튜닝 {e['dataset']['tuning']} / 최종 {e['dataset']['final']}), "
                  f"Food-101 검증 샤드, 시드 {e['dataset']['seed']}"]
        rows = []
        for key in ["before_final", "after_final"]:
            if key not in e["summary"]:
                rows.append([key, "측정 전", None, None, None, None, None, None, None])
                continue
            s = e["summary"][key]
            rows.append([key, s["n"], f"{s['top1_acc']}%", f"{s['top3_acc']}%", s["latency_ms_mean"], s["latency_ms_max"],
                         s["kcal_n"], s["kcal_mae_correct_class"], s["kcal_mape_correct_class"]])
        lines += [md_table(["구분", "n", "top-1", "top-3", "지연 평균(ms)", "지연 최대(ms)", "kcal 비교 n",
                            "kcal MAE", "kcal MAPE(%)"], rows), ""]
        if e.get("per_food_final"):
            lines += ["### 음식별 예측 칼로리와 기준 칼로리 (최종 세트, 보조 정답 클래스)"]
            lines += [md_table(["음식", "정답 라벨", "예측 1위", "예측 kcal", "기준 kcal(보조)", "인식 정답"],
                               [[f["name_ko"], f["gold"], f["pred"], f["pred_kcal"], f["ref_kcal"], "O" if f["correct"] else "X"]
                                for f in e["per_food_final"]]), ""]
        lines += ["> 칼로리 기준은 USDA 기반 대리 정답(18개 클래스)이며 사진별 실측이 아닙니다. 표본이 작아 참고용입니다.", ""]

    lines += ["## 8. 검증 결과 요약", f"- 모니터링 성공 {len(ok)}건 / 실패 {len(fail)}건",
              f"- 전환 시각: {switch.isoformat() if switch else '없음'} (배포 시작 {deploy_start.isoformat() if deploy_start else '-'})", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="monitor")
    ap.add_argument("--eval", default=None)
    ap.add_argument("--service-url", default="http://127.0.0.1:8000")
    ap.add_argument("--md", default="monitor/summary.md")
    args = ap.parse_args()
    text = build(args)
    Path(args.md).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
