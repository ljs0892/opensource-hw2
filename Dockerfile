# syntax=docker/dockerfile:1.7
#
# 음식 사진 분류 · 칼로리 추정 앱 이미지
#   1) deps    : CPU 전용 PyTorch + requirements.txt 설치
#   2) model   : config/model.json 에 고정된 리비전의 모델 다운로드 + SHA-256 확인 + 추론 검증
#   3) runtime : 모델과 앱만 담은 최종 이미지 (비루트 사용자로 실행)
#
# 빌드:  docker build -t food-calorie-app .
# 실행:  docker run --rm -p 127.0.0.1:8000:8000 food-calorie-app
#        (호스트에서는 127.0.0.1로만 접근 가능하도록 포트를 게시합니다)

ARG PYTHON_IMAGE=python:3.14.7-slim-trixie

# ---------------------------------------------------------------------------
# 1) 의존성
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS deps

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY requirements.txt .

# torch 는 CPU 휠을 먼저 설치한다. 기본 PyPI 휠은 CUDA 패키지(수 GB)를 끌어온다.
# requirements.txt 의 torch==2.14.1 은 +cpu 휠로 이미 만족되므로 다시 받지 않는다.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        torch==2.14.1 \
 && pip install -r requirements.txt \
 && python3 -c "import torch, sys; assert torch.version.cuda is None, 'CUDA 빌드가 설치되었습니다'; print('torch', torch.__version__, 'cpu-only')"

# ---------------------------------------------------------------------------
# 2) 모델 준비와 검증
# ---------------------------------------------------------------------------
FROM deps AS model

WORKDIR /app
ENV HF_HUB_DISABLE_TELEMETRY=1

COPY config/ config/
COPY app/ app/
COPY scripts/ scripts/
COPY tests/fixtures/images/bibimbap_seoul_beef.jpg tests/fixtures/images/

# 고정 리비전 다운로드 + 가중치 SHA-256 확인 (불일치하면 빌드 실패)
RUN python3 scripts/download_model.py

# 모델 로드 + 실제 추론 검증 (실패하면 빌드 실패)
RUN python3 scripts/verify_model.py

# ---------------------------------------------------------------------------
# 3) 실행 이미지
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1

RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

COPY --from=deps /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

WORKDIR /app
COPY app/ app/
COPY static/ static/
COPY config/ config/
COPY data/ data/
COPY scripts/ scripts/
COPY --from=model /app/models/ models/

RUN mkdir -p logs && chown app:app logs

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

# 컨테이너 안에서는 0.0.0.0 으로 바인딩해야 docker 포트 게시가 동작한다.
# 호스트 노출은 `-p 127.0.0.1:8000:8000` 으로 로컬호스트에만 허용한다.
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
