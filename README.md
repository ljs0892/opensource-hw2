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
