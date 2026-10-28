"""음식 사진 분류·칼로리 추정 FastAPI 앱.

- 127.0.0.1에서만 동작한다 (설정 파일 host가 루프백이 아니면 기동을 거부).
- 업로드 이미지는 메모리에서만 처리하고 디스크에 저장하지 않는다.
- 예측 로그(시간, 예측 클래스, 신뢰도, 지연시간)와 피드백은 JSON Lines로 logs/에 남긴다.
"""

import io
import logging
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.classifier import FoodClassifier
from app.config import CONFIG, PROJECT_ROOT, resolve
from app.nutrition import CalorieTable
from app.prediction_log import JsonlLog

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("food_app")

LOOPBACK_HOST = "127.0.0.1"
DISCLAIMER = (
    "이 결과는 AI 추정치이며 실제와 다를 수 있습니다. "
    "사진 속 음식의 양은 추정하지 않으며, 칼로리는 음식 종류별 1인분 기준 대략값입니다."
)
MAX_RECENT_PREDICTIONS = 1000

MODEL_CFG = CONFIG["model"]
INFER_CFG = CONFIG["inference"]
LOG_CFG = CONFIG["logs"]
ALLOWED_FORMATS = set(INFER_CFG["allowed_formats"])

if CONFIG["server"]["host"] != LOOPBACK_HOST:
    raise RuntimeError(f"host는 {LOOPBACK_HOST}만 허용됩니다 (설정값: {CONFIG['server']['host']})")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


class FeedbackIn(BaseModel):
    prediction_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    correct: bool
    actual_label: str | None = Field(default=None, max_length=64)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.classifier = None
    app.state.load_error = None
    app.state.nutrition = CalorieTable(resolve(CONFIG["data"]["calorie_table"]))
    app.state.prediction_log = JsonlLog(resolve(LOG_CFG["prediction_log"]))
    app.state.feedback_log = JsonlLog(resolve(LOG_CFG["feedback_log"]))
    app.state.recent = OrderedDict()
    app.state.recent_lock = Lock()

    model_dir = resolve(MODEL_CFG["local_dir"])
    try:
        if not model_dir.is_dir():
            raise FileNotFoundError(
                f"모델 폴더가 없습니다: {MODEL_CFG['local_dir']}. "
                "먼저 `PYTHONPATH=.vendor python3 scripts/download_model.py`를 실행하세요."
            )
        app.state.classifier = FoodClassifier(model_dir, model_info(), INFER_CFG["top_k"])
        missing = app.state.nutrition.missing_labels(app.state.classifier.labels)
        if missing:
            log.warning("칼로리 테이블에 없는 라벨: %s", missing)
        log.info("모델 로드 완료: %s@%s", MODEL_CFG["model_id"], MODEL_CFG["revision"][:8])
    except Exception as exc:  # 모델 실패 시에도 서버는 떠서 /health로 원인을 보여준다
        app.state.load_error = f"{type(exc).__name__}: {exc}"
        log.exception("모델 로드 실패")
    yield


app = FastAPI(title="음식 사진 분류·칼로리 추정", version=MODEL_CFG["model_version"], lifespan=lifespan)
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_request", "message": "요청 형식이 올바르지 않습니다."}},
    )


def model_info() -> dict:
    return {
        "model_id": MODEL_CFG["model_id"],
        "revision": MODEL_CFG["revision"],
        "model_version": MODEL_CFG["model_version"],
        "device": MODEL_CFG["device"],
        "architecture": MODEL_CFG["architecture"],
        "training_data": MODEL_CFG["training_data"],
        "reported_eval_accuracy": MODEL_CFG["reported_eval_accuracy"],
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def read_limited_body(request: Request, max_bytes: int) -> bytes:
    """요청 본문을 메모리에 읽는다.

    제한을 넘으면 더 이상 저장하지 않고 본문을 끝까지 버린 뒤 413을 돌려준다.
    (읽지 않고 끊으면 클라이언트가 TCP 연결 리셋을 받아 오류 메시지를 볼 수 없다.)
    """
    too_large = AppError(413, "too_large", f"파일이 너무 큽니다. {max_bytes // (1024 * 1024)}MB 이하만 허용됩니다.")
    chunks: list[bytes] = []
    total = 0
    exceeded = False
    async for chunk in request.stream():
        total += len(chunk)
        if exceeded:
            continue
        if total > max_bytes:
            exceeded = True
            chunks.clear()
            continue
        chunks.append(chunk)
    if exceeded:
        raise too_large
    return b"".join(chunks)


def decode_image(data: bytes) -> Image.Image:
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()
        fmt = probe.format
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise AppError(400, "invalid_image", "이미지를 읽을 수 없습니다. JPEG, PNG, WEBP 파일인지 확인하세요.") from exc
    if fmt not in ALLOWED_FORMATS:
        raise AppError(415, "unsupported_format", "지원하지 않는 형식입니다. JPEG, PNG, WEBP만 가능합니다.")
    return image.convert("RGB")


def remember_prediction(prediction_id: str, top_label: str) -> None:
    recent: OrderedDict = app.state.recent
    with app.state.recent_lock:
        recent[prediction_id] = top_label
        while len(recent) > MAX_RECENT_PREDICTIONS:
            recent.popitem(last=False)


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(PROJECT_ROOT / "static" / "index.html")


@app.get("/health")
async def health(request: Request):
    state = request.app.state
    loaded = state.classifier is not None
    return {
        "status": "ok" if loaded else "degraded",
        "model_loaded": loaded,
        "load_error": state.load_error,
        "loaded_at": state.classifier.loaded_at if loaded else None,
        "model": model_info(),
        "num_labels": len(state.classifier.labels) if loaded else None,
        "config_version": CONFIG["config_version"],
        "inference": {
            "top_k": INFER_CFG["top_k"],
            "confidence_threshold": INFER_CFG["confidence_threshold"],
            "max_upload_mb": INFER_CFG["max_upload_bytes"] // (1024 * 1024),
            "allowed_formats": INFER_CFG["allowed_formats"],
        },
        "server": {"host": LOOPBACK_HOST, "port": CONFIG["server"]["port"]},
    }


@app.get("/api/calories")
async def calories(request: Request):
    return {
        "unit": request.app.state.nutrition.unit,
        "notice": request.app.state.nutrition.notice,
        "items": request.app.state.nutrition.all_rows(),
    }


@app.post("/api/predict")
async def predict(request: Request):
    state = request.app.state
    if state.classifier is None:
        raise AppError(503, "model_not_ready", "모델이 아직 준비되지 않았습니다. 서버 로그와 /health를 확인하세요.")

    data = await read_limited_body(request, INFER_CFG["max_upload_bytes"])
    if not data:
        raise AppError(400, "empty_file", "빈 파일입니다. 음식 사진을 선택해 주세요.")

    started = time.perf_counter()
    image = await run_in_threadpool(decode_image, data)
    top_k = await run_in_threadpool(state.classifier.predict, image)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    threshold = INFER_CFG["confidence_threshold"]
    top_label, top_conf = top_k[0]
    status = "ok" if top_conf >= threshold else "uncertain"
    prediction_id = uuid.uuid4().hex

    candidates = []
    for label, conf in top_k:
        entry = {
            "label": label,
            "name_ko": state.nutrition.name_ko(label),
            "confidence": round(conf, 4),
        }
        if status == "ok":
            entry["nutrition"] = state.nutrition.lookup(label)
        candidates.append(entry)

    state.prediction_log.append(
        {
            "ts": now_iso(),
            "prediction_id": prediction_id,
            "model_id": MODEL_CFG["model_id"],
            "model_version": MODEL_CFG["model_version"],
            "predicted_label": top_label,
            "confidence": round(top_conf, 4),
            "status": status,
            "latency_ms": latency_ms,
        }
    )
    remember_prediction(prediction_id, top_label)

    return {
        "prediction_id": prediction_id,
        "status": status,
        "confidence_threshold": threshold,
        "message": (
            "인식 결과입니다. 아래 칼로리는 1인분 기준 대략값입니다."
            if status == "ok"
            else "인식 불확실: 음식으로 확신할 수 없거나 신뢰도가 낮습니다. 더 선명하고 음식이 중앙에 보이는 사진으로 다시 시도해 보세요."
        ),
        "top_k": candidates,
        "latency_ms": latency_ms,
        "model": model_info(),
        "disclaimer": DISCLAIMER,
    }


@app.post("/api/feedback")
async def feedback(body: FeedbackIn, request: Request):
    state = request.app.state
    if body.actual_label is not None and not state.nutrition.has_label(body.actual_label):
        raise AppError(422, "invalid_label", "알 수 없는 음식 라벨입니다.")
    with state.recent_lock:
        predicted = state.recent.get(body.prediction_id)
    state.feedback_log.append(
        {
            "ts": now_iso(),
            "prediction_id": body.prediction_id,
            "known_prediction": predicted is not None,
            "predicted_label": predicted,
            "correct": body.correct,
            "actual_label": body.actual_label,
        }
    )
    return {"ok": True, "known_prediction": predicted is not None}
