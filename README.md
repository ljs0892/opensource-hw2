# 음식 사진 분류 · 칼로리 추정 (로컬 웹앱)

음식 사진을 올리면 **상위 3개 후보와 신뢰도**를 보여주고, 음식 종류별 **1인분 기준 칼로리 대략값**을 함께 표시하는 로컬 웹앱입니다. 사전 학습 모델(Food-101 기반)을 맥북 CPU에서 추론하며, 서버는 `127.0.0.1`에서만 실행됩니다.

- 결과는 **추정치**이며 실제와 다를 수 있습니다. 사진 속 음식의 양은 추정하지 않습니다.
- 신뢰도가 낮거나 음식이 아닌 사진은 **"인식 불확실"**로 안내하고 칼로리를 표시하지 않습니다.
- 업로드한 사진은 디스크에 저장하지 않고 메모리에서만 처리합니다.
- 예측 로그(시간, 예측 클래스, 신뢰도, 지연시간)와 맞음/틀림 피드백은 `logs/`에 JSON Lines로 기록합니다. 이미지는 기록하지 않습니다.

## 요구 사항

- macOS (Apple Silicon에서 검증, CPU 추론만 사용)
- `python3` (검증 환경: Python 3.14.7, Homebrew 설치)
- 인터넷 연결 (최초 설치와 모델 다운로드 시에만 필요, 약 340MB)
- 가상환경은 필요하지 않습니다.

## 설치 방법

이 폴더(`upload/`)에서 다음을 실행합니다.

```zsh
cd upload
python3 -m pip install --target ./.vendor -r requirements.txt
```

macOS의 Homebrew Python은 `EXTERNALLY-MANAGED`로 보호되어 있어서 `pip install` 또는 `pip install --user`가 막힐 수 있습니다. 위 명령은 패키지를 이 폴더 안의 `.vendor/`에 설치하므로 시스템 Python을 변경하지 않습니다. `--break-system-packages`는 사용하지 마세요.

## 모델 준비 방법

모델 가중치는 저장소에 포함되어 있지 않습니다. 설정 파일(`config/model.json`)에 고정된 리비전을 한 번 내려받아야 합니다.

```zsh
PYTHONPATH=.vendor python3 scripts/download_model.py
```

- 모델: `nateraw/food` (Apache-2.0), 리비전 `8991abd49ea01ebf502aeda51d4f12a59c603e01`
- 저장 위치: `models/nateraw-food/` (약 340MB)
- 이미 받은 경우 다시 실행해도 안전합니다.

## 실행 방법

```zsh
./run.sh
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. 종료는 Ctrl+C입니다.

포트를 바꾸려면 `PORT=8001 ./run.sh`처럼 실행하세요. 호스트는 보안상 `127.0.0.1`로 고정되어 있습니다.

- 모델이 없으면 화면과 `/health`에 "모델 로드 실패"와 원인이 표시됩니다. 위의 모델 준비 단계를 실행한 뒤 서버를 다시 시작하세요.

## 사용 방법

1. "사진 선택하기"로 JPEG, PNG, WEBP 사진을 고릅니다. 최대 10MB입니다.
2. 미리보기를 확인하고 "분석하기"를 누릅니다.
3. 상위 3개 후보와 신뢰도, 1인분 기준 칼로리를 확인합니다.
4. "맞아요" 또는 "틀려요"로 결과를 알려 줄 수 있습니다. 틀렸다면 실제 음식을 골라 줄 수도 있습니다.

## Docker로 실행하기

Docker가 설치되어 있다면 가상환경과 로컬 설치 없이 실행할 수 있습니다. 빌드 과정에서 모델을 내려받고, SHA-256을 확인하고, 실제 사진으로 추론까지 검증합니다.

```zsh
docker build -t food-calorie-app .
docker run --rm -p 127.0.0.1:8000:8000 food-calorie-app
```

- 브라우저에서 http://127.0.0.1:8000 을 엽니다.
- 포트는 `127.0.0.1`에만 게시됩니다. 같은 네트워크의 다른 기기에서는 접근할 수 없습니다.
- 컨테이너 안에서는 `0.0.0.0`에 바인딩합니다. Docker 포트 게시가 동작하려면 필요하고, 실제 외부 노출은 위 `127.0.0.1:` 설정이 막습니다.
- 이미지는 CPU 전용 PyTorch를 사용하며 약 2.3GB입니다. 빌드 중 모델(약 340MB)을 Hugging Face에서 받으므로 빌드에는 인터넷 연결이 필요합니다.
- 컨테이너는 비루트 사용자(`app`, uid 10001)로 실행됩니다. 업로드 이미지는 저장되지 않으며, `logs/`는 컨테이너 안에만 생깁니다. 호스트에 로그를 남기려면 `-v "$PWD/logs:/app/logs"`를 추가하세요.
- 현재 빌드는 `linux/amd64`입니다. Apple Silicon에서는 에뮬레이션으로 실행되므로 느릴 수 있습니다.

## CI: GitHub Actions로 자동 빌드·업로드

`.github/workflows/ci.yml`은 다음 순서로 동작합니다.

1. `main` 브랜치에 push하면 이미지를 빌드합니다. 풀 리퀘스트에서는 빌드와 검증까지만 합니다.
2. 빌드 중 모델 해시 확인과 추론 검증이 통과해야 합니다.
3. 빌드된 이미지를 `127.0.0.1:8000`으로 띄워 `scripts/smoke_test.py`로 `/health`와 `/api/predict`를 확인합니다.
4. 통과하면 Docker Hub에 `sha-<커밋>` 태그와, `main`이면 `latest` 태그로 업로드합니다.

GitHub 저장소의 **Settings → Secrets and variables → Actions**에 다음 두 값을 등록해야 합니다.

| 이름 | 값 |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub 사용자 이름 |
| `DOCKERHUB_TOKEN` | Docker Hub 액세스 토큰 (비밀번호가 아닌 Access Token 권장, 쓰기 권한) |

- Docker Hub 저장소 이름은 `<DOCKERHUB_USERNAME>/food-calorie-app`입니다. 첫 push 때 저장소가 없으면 Docker Hub에서 미리 만들어 두세요.
- 액션은 커밋 SHA로 고정되어 있습니다. 버전을 올릴 때는 `ci.yml`의 주석 버전과 SHA를 함께 바꾸세요.

## 로컬 무중단 배포 (self-hosted Runner, macOS)

`.github/workflows/deploy.yml`은 `CI · Docker build & push`가 `main`에서 성공하면, 이 Mac의 self-hosted Runner에서 방금 올라간 이미지(`sha-<커밋 앞 7자리>`)로 배포합니다. 접속 주소는 `http://127.0.0.1:8000`로 그대로입니다.

- 구조: `food-router`(nginx)가 8000 포트를 점유하고, 앱은 블루/그린 두 컨테이너(`food-app-blue`, `food-app-green`)로 운영합니다.
- 전환: 유휴 색에 새 이미지를 띄우고 컨테이너 안에서 스모크 테스트를 통과하면 라우터 upstream을 바꾸고 `nginx -s reload`로 전환합니다. 검증에 실패하면 라우터는 건드리지 않습니다.
- 최초 1회: 무중단 구성 이전의 단일 컨테이너(`food-calorie-app`)에서 옮겨 올 때 포트를 넘기는 약 6초의 공백이 있습니다.
- 모니터링: 배포 전부터 독립 프로세스(`scripts/monitor.py`)가 고정 사진으로 `/api/predict`를 1초 간격 호출해 최대 100건을 기록합니다(배포 전 확인, 배포, 배포 후 30초 관찰 포함). 배포 완료 후 30초 더 관찰하고 요약(`scripts/monitor_report.py`)을 Actions Summary에 출력합니다. 전체 로그는 `deploy-monitor-<run_id>` 아티팩트(UTF-8)로 올라갑니다.
- 로컬에서 직접 실행: `IMAGE=<계정>/food-calorie-app:sha-<커밋> scripts/deploy_bluegreen.sh`
- 로그와 라우터 상태는 `~/food-calorie-app-data/`에 있으며 저장소 밖에 있습니다.

필요 조건:
- Docker Desktop이 실행 중이어야 합니다.
- Runner는 `~/actions-runner`에 설치되어 있고, `svc.sh`로 launchd 서비스로 등록되어 있습니다(`./svc.sh status`로 확인).
- Runner 라벨 `self-hosted`, `macOS`, `ARM64`를 사용합니다.
- Runner 설치 파일과 자격 증명은 Git에 포함되지 않습니다(`.gitignore` 참고).

## 인식 성능과 평가

- 평가 세트: Food-101 검증 샤드에서 클래스당 1장씩 100장(시드 2026)을 뽑아 튜닝 30장, 최종 평가 70장으로 나눴습니다. 이미지는 `eval/`에만 두고 Git에 올리지 않습니다(라이선스: 원 데이터셋은 scientific fair use 범위만 허용).
- 개선 시도는 2회까지만 허용했습니다. 1회차는 전처리(좌우 반전 TTA)이고, 2회차(칼로리 테이블)는 정답 칼로리가 없어 적용하지 않았습니다.
- 결과 요약: `docs/evaluation_summary.json` (이미지·원본 결과 제외).
- 평가 스크립트: `scripts/build_eval_set.py`, `scripts/evaluate.py`, `scripts/make_eval_summary.py`.
- 칼로리 정답은 USDA 기반 **보조(proxy) 정답 18개 클래스**뿐이라 사진별 실측이 아닙니다. 표본이 작아 칼로리 수치는 참고용입니다.
- 사진 기반 양(g) 추정은 구현하지 않았습니다. 화면과 API의 `estimated_portion_g`는 음식 종류별 **표준 1인분 g**입니다.

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 모델 ID, 리비전, 버전, 라벨 수, 임계값, 로드 상태 |
| GET | `/api/calories` | 음식 종류별 1인분 칼로리 테이블 |
| POST | `/api/predict` | 본문에 이미지 바이트를 보냄 (`Content-Type: image/jpeg` 등) |
| POST | `/api/feedback` | `{"prediction_id": "...", "correct": true}` 형식 (틀린 경우 `actual_label` 추가 가능) |

```zsh
curl -s --data-binary @"내사진.jpg" -H "Content-Type: image/jpeg" http://127.0.0.1:8000/api/predict
```

## 설정 변경

`config/model.json`에서 다음을 바꿀 수 있습니다.

- `model.model_id`, `model.revision`, `model.local_dir`: 다른 모델로 교체할 때. 바꾼 뒤 모델 준비 단계를 다시 실행합니다.
- `inference.top_k`: 보여 줄 후보 수
- `inference.confidence_threshold`: "인식 불확실" 기준 (기본 0.5)
- `inference.max_upload_bytes`: 업로드 최대 크기

칼로리 값은 `data/calorie_table.json`에서 수정합니다. 키는 모델 라벨 이름과 같아야 합니다.

## 프로젝트 구조

```
app/                  FastAPI 앱 (분류기, 칼로리 조회, JSONL 로그)
static/               웹 화면 (HTML, CSS, JavaScript)
config/model.json     모델·추론·로그 설정
data/calorie_table.json  음식별 1인분 칼로리 대략값
scripts/download_model.py  고정 리비전 모델 다운로드
run.sh                실행 스크립트 (127.0.0.1 바인딩)
requirements.txt      런타임 의존성 (검증 버전 고정)
Dockerfile            컨테이너 이미지 빌드 (모델 준비·검증 포함)
.github/workflows/ci.yml  빌드·스모크 테스트·Docker Hub 업로드
scripts/verify_model.py   모델 로드·추론 검증 (빌드에서 실행)
scripts/smoke_test.py     실행 중인 서버 스모크 테스트
tests/fixtures/images/    검증용 사진 1장 (출처: SOURCES.md)
```

실행 중에는 `.vendor/`, `models/`, `logs/`가 생깁니다. 이 폴더들은 Git에 올리지 마세요(`.gitignore`에 포함).

## 한계

- 모델은 101개 음식 클래스만 분류합니다. 음식이 아닌 사진도 어떤 음식으로 분류되므로, 음식이 아님은 신뢰도 임계값으로만 판단합니다. 신뢰도가 높게 나오는 비음식 사진은 놓칠 수 있습니다.
- 칼로리는 일반적인 1인분 기준의 대략값입니다. 실제 칼로리와 차이가 클 수 있습니다.
- 의료·식단 관리 용도로 쓰기에는 적합하지 않습니다.

## 라이선스

- 이 앱 코드: 프로젝트 소유자가 정하는 라이선스를 따릅니다. (추가 필요)
- 모델 `nateraw/food`: Apache-2.0. 원본 모델 카드를 확인하세요.
- Food-101 데이터셋 자체는 포함되지 않습니다.
