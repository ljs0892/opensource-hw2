"""독립 모니터링 프로세스: 고정 음식 사진으로 /api/predict 를 1초 간격 호출하고 결과를 기록한다.

    # 실행 (CD 워크플로에서 배포 전에 백그라운드로 시작)
    python3 scripts/monitor.py run --url http://127.0.0.1:8000/api/predict \
        --image tests/fixtures/images/bibimbap_seoul_beef.jpg --out monitor \
        --phase-log monitor/phases.log --stop-file monitor/STOP

    # 배포 전 정상 응답 확인 (연속 성공 N회까지 대기)
    python3 scripts/monitor.py wait-ok --log monitor/requests.jsonl --consecutive 10 --timeout 180

출력 (UTF-8)
- requests.jsonl : 요청별 원자료 (JSON Lines)
- monitor.log    : 사람이 읽는 요청별 한 줄 로그
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def current_phase(phase_log: Path | None) -> str:
    if not phase_log or not phase_log.exists():
        return "PRE"
    lines = [ln for ln in phase_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return lines[-1].split()[1] if lines and len(lines[-1].split()) >= 2 else "PRE"


def call_once(url: str, image: bytes) -> dict:
    req = urllib.request.Request(url, data=image, method="POST", headers={"Content-Type": "image/jpeg"})
    started, t0 = now_iso(), time.perf_counter()
    code, body, error = None, None, None
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code, body = resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            body = json.loads(exc.read())
        except Exception:
            body = None
        error = f"HTTP {exc.code}"
    except Exception as exc:  # 연결 실패, 타임아웃 등
        error = f"{type(exc).__name__}: {exc}"
    wall_ms = (time.perf_counter() - t0) * 1000
    ended = now_iso()

    top = (body or {}).get("top_k") or []
    top1 = top[0] if top else {}
    nut = top1.get("nutrition") or {}
    app_status = (body or {}).get("status")
    success = code == 200 and bool(top) and app_status in ("ok", "uncertain")
    if code == 200 and not success:
        error = error or "응답 형식 이상"
    return {
        "start_utc": started,
        "end_utc": ended,
        "wall_ms": round(wall_ms, 1),
        "http_status": code,
        "success": success,
        "error": error,
        "app_status": app_status,
        "recognized_label": top1.get("label"),
        "recognized_name_ko": top1.get("name_ko"),
        "confidence": top1.get("confidence"),
        "estimated_portion_g": (body or {}).get("estimated_portion_g"),
        "kcal": nut.get("kcal"),
        "server_latency_ms": (body or {}).get("latency_ms"),
        "app_version": (body or {}).get("app_version"),
    }


def text_line(seq: int, phase: str, r: dict) -> str:
    status = "성공" if r["success"] else "실패"
    food = f"{r['recognized_name_ko']}({r['recognized_label']}) {r['confidence']*100:.1f}%" if r["recognized_label"] else "-"
    portion = f"표준 1인분 {r['estimated_portion_g']}g" if r["estimated_portion_g"] else "-"
    kcal = f"{r['kcal']} kcal" if r["kcal"] is not None else "-"
    err = f" | 오류: {r['error']}" if r["error"] else ""
    return (f"[#{seq:04d}] {r['start_utc']} ~ {r['end_utc']} | 단계 {phase} | HTTP {r['http_status']} | "
            f"응답 {r['wall_ms']:.0f}ms | {status} | {food} | {portion} | {kcal} | 버전 {r['app_version']}{err}")


def run(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    image = Path(args.image).read_bytes()
    phase_log = Path(args.phase_log) if args.phase_log else None
    stop_file = Path(args.stop_file)
    if stop_file.exists():
        stop_file.unlink()
    jl = (out / "requests.jsonl").open("a", encoding="utf-8")
    tl = (out / "monitor.log").open("a", encoding="utf-8")
    header = f"# 모니터 시작 {now_iso()} | 대상 {args.url} | 이미지 {args.image} | 간격 {args.interval}s"
    tl.write(header + "\n")
    tl.flush()
    print(header, flush=True)

    started = time.monotonic()
    seq = 0
    next_tick = time.monotonic()
    while True:
        if stop_file.exists():
            break
        if time.monotonic() - started > args.max_seconds:
            tl.write(f"# 최대 실행 시간 {args.max_seconds}s 초과로 종료\n")
            break
        seq += 1
        phase = current_phase(phase_log)
        rec = call_once(args.url, image)
        rec = {"seq": seq, "phase": phase, **rec}
        jl.write(json.dumps(rec, ensure_ascii=False) + "\n")
        jl.flush()
        line = text_line(seq, phase, rec)
        tl.write(line + "\n")
        tl.flush()
        print(line, flush=True)
        next_tick += args.interval
        time.sleep(max(0.0, next_tick - time.monotonic()))

    footer = f"# 모니터 종료 {now_iso()} | 요청 {seq}건"
    tl.write(footer + "\n")
    tl.close()
    jl.close()
    print(footer, flush=True)
    return 0


def wait_ok(args) -> int:
    log = Path(args.log)
    deadline = time.monotonic() + args.timeout
    consecutive, seen = 0, 0
    while time.monotonic() < deadline:
        if log.exists():
            lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if len(lines) > seen:
                for ln in lines[seen:]:
                    rec = json.loads(ln)
                    consecutive = consecutive + 1 if rec["success"] else 0
                    print(f"[사전 확인] 요청 #{rec['seq']} {'성공' if rec['success'] else '실패'} | 연속 성공 {consecutive}/{args.consecutive}", flush=True)
                seen = len(lines)
                if consecutive >= args.consecutive:
                    print(f"[사전 확인 통과] 연속 {consecutive}회 성공 → 재배포를 진행합니다.", flush=True)
                    return 0
        time.sleep(1)
    print(f"[사전 확인 실패] {args.timeout}초 안에 연속 {args.consecutive}회 성공이 없었습니다.", file=sys.stderr, flush=True)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--url", required=True)
    r.add_argument("--image", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--interval", type=float, default=1.0)
    r.add_argument("--phase-log", default=None)
    r.add_argument("--stop-file", required=True)
    r.add_argument("--max-seconds", type=int, default=1800)
    r.set_defaults(func=run)

    w = sub.add_parser("wait-ok")
    w.add_argument("--log", required=True)
    w.add_argument("--consecutive", type=int, default=10)
    w.add_argument("--timeout", type=int, default=180)
    w.set_defaults(func=wait_ok)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
