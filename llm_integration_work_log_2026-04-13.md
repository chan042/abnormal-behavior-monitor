# 로컬 LLM 연동 작업 정리

작성일: 2026-04-13

## 1. 작업 목표

이상행동 탐지 엔진이 실신 또는 배회 이벤트를 감지한 뒤, 해당 이벤트의 대표 프레임 1장을 로컬 LLM에 전달하여 관제용 상황 설명을 자동 생성하도록 연동했다.  
우선순위는 보안과 운영 독립성을 고려한 로컬 모델 적용이며, 최종 선택 모델은 `Gemma 4 E4B`이다.

## 2. 최종 아키텍처 결정

- 연동 방식은 `백엔드 -> 로컬 HTTP 추론 서버(Ollama 호환)` 구조로 확정했다.
- 이벤트 저장과 대시보드 반영은 즉시 수행하고, 상황 설명 생성은 비동기 worker가 후처리하도록 구성했다.
- 설명 생성 실패 시 탐지 파이프라인을 멈추지 않고 기존 규칙 기반 문구를 유지하도록 설계했다.
- 모델 후보 비교 결과 `E2B`보다 `E4B`가 묘사 정확도와 세부 품질이 더 안정적이어서 `E4B`를 유지하기로 결정했다.

## 3. 백엔드 구현 내역

### 3-1. Scene Description 서비스 계층 추가

다음 파일을 중심으로 상황 설명 전용 서비스 계층을 추가했다.

- `backend/app/scene_description/service.py`
- `backend/app/events/storage.py`
- `backend/app/main.py`
- `backend/app/pipeline.py`
- `backend/app/live/service.py`
- `backend/app/live/browser_service.py`
- `backend/app/api/fastapi_app.py`

적용 내용은 다음과 같다.

- `SceneDescriptionService` 단일 worker 큐를 추가했다.
- 이벤트가 저장될 때 `description_status=pending` 상태로 적재되도록 수정했다.
- worker가 이벤트 JSONL을 다시 읽고, 설명 생성 결과를 원본 이벤트 레코드에 반영하도록 구성했다.
- FastAPI 시작 시 `pending` 이벤트를 다시 스캔해 재큐잉하도록 구현했다.
- CLI 및 서버 실행 옵션에 아래 설정을 추가했다.
  - `--enable-scene-description`
  - `--scene-llm-model`
  - `--scene-llm-host`
  - `--scene-llm-timeout`
  - `--scene-llm-keep-alive`
- 기존 파이프라인, 라이브 모니터, 브라우저 라이브 경로 모두 동일한 설명 생성 큐를 사용하도록 통합했다.

### 3-2. Ollama 호환 로컬 LLM 호출 구현

`backend/app/scene_description/service.py` 안에 `OllamaSceneDescriptionProvider`를 추가했다.

- 호출 엔드포인트는 `POST /api/chat`
- 모델은 기본값 `gemma4:e4b`
- `stream: false`
- `format: json`
- 입력 이미지는 base64 인코딩 후 `images` 배열로 전송
- 응답은 assistant message의 `content`를 읽고 후처리한다

즉, 일반 외부 API 키 기반 구조가 아니라, 로컬 머신에서 실행 중인 Ollama 서버에 HTTP 요청을 보내는 형태로 동작한다.

### 3-3. 이벤트 스키마 및 저장 구조 확장

다음 필드를 `EventRecord`와 API 응답에 추가했다.

- `updated_at`
- `description_status`
- `description_source`
- `description_generated_at`
- `description_error`
- `operator_note`

`description_status`는 아래 4가지 상태로 고정했다.

- `pending`
- `completed`
- `failed`
- `fallback`

이를 통해 프론트에서 AI 설명 생성 상태와 관제사 메모 상태를 분리해서 다룰 수 있게 만들었다.

## 4. 프롬프트 엔지니어링 및 구조화 출력

### 4-1. 초기 프롬프트 방향

초기 목표는 한국어 1문장 요약이었지만, 묘사 품질 편차와 누락 문제를 줄이기 위해 자유문장 대신 구조화 JSON 응답을 요구하는 방식으로 개선했다.

### 4-2. 최종 출력 구조

LLM은 아래 키를 가진 JSON 객체 하나만 반환하도록 강제했다.

- `age_group`
- `gender`
- `upper_clothing`
- `lower_clothing`
- `action_posture`
- `location`
- `event_phrase`

강제 규칙은 다음과 같다.

- 나이대는 사전 정의된 허용값만 사용
- 성별은 `남성 | 여성 | 확인 어려움`만 사용
- 상의/하의는 색상과 종류를 함께 기술
- 자세/행동과 위치는 분리
- 이벤트 문구는 `실신이 의심됩니다`, `실신 상황으로 추정됩니다`, `배회가 의심됩니다`, `배회 상황으로 추정됩니다` 중 이벤트 유형에 맞는 값만 허용

### 4-3. 응답 검증 및 후처리

구조화 JSON이 깨지거나 규칙을 만족하지 못하는 경우를 대비해 후처리 로직을 추가했다.

- JSON 블록 외 불필요한 텍스트 제거
- 중첩 payload 탐색
- 허용값 정규화
- 배지/박스/UI 표현 제거
- 길이 제한 검증
- 필수 슬롯 누락 시 fallback 전환

최종적으로 관제 대시보드에는 아래 형태의 자연어 문장으로 재조합해 저장한다.

`연령대 50대, 성별 남성, 상의 파란 체크 셔츠, 하의 검은 바지, 위치 복도, 행동/자세 바닥에 쓰러져 움직임이 거의 없는 상태, 실신이 의심됩니다.`

## 5. LLM 입력 이미지 선택 방식 개선

### 5-1. 단순 스냅샷 전달에서 오버레이 우선 방식으로 변경

배회 이벤트의 경우 프레임 안에 여러 사람이 보이면 LLM이 이벤트 주체가 아닌 다른 사람까지 설명하는 문제가 있었다. 이를 줄이기 위해 설명 입력 이미지를 아래 순서로 선택하도록 수정했다.

- 이벤트 오버레이 클립이 있으면 그 중간 프레임을 우선 사용
- 가능하면 `target_bbox` 기준 crop 이미지를 추가 생성
- 오버레이 클립이 없으면 기존 snapshot 기준으로 동일 crop 적용

### 5-2. 이벤트 주체 고정 규칙

프롬프트에 아래 규칙을 명시적으로 추가했다.

- `AI EVENT` 배지와 강조 박스가 붙은 사람 한 명만 설명
- 배지가 없는 다른 사람은 설명에서 제외
- 배지, 박스, 오버레이 자체는 묘사하지 않음

이 변경으로 “프레임에 두 사람이 있어 두 사람 모두 배회 중이라고 설명하는 문제”를 완화했다.

## 6. 프론트엔드 반영 내역

관련 파일은 다음과 같다.

- `frontend/src/types/dashboard.ts`
- `frontend/src/components/dashboard/dashboard-app.tsx`

적용 내용은 다음과 같다.

- 이벤트 타입에 새 설명 관련 필드를 반영했다.
- 설명 표시 상태를 `pending/completed/failed/fallback`에 맞게 처리하도록 정리했다.
- 별도 AI 설명 컴포넌트를 제거한 뒤, 메모 영역이 기본적으로 `operator_note || description`을 표시하도록 바꿨다.
- 즉, AI가 생성한 초안이 먼저 메모에 보이고, 관제사가 그 내용을 수정하거나 추가 메모를 남긴 뒤 저장할 수 있는 구조로 맞췄다.
- 오버레이 영상을 우선 보여주도록 정리했다.
- 오버레이 파일 갱신 후에도 브라우저가 이전 MP4를 재사용하지 않도록 `updated_at` 기반 cache-busting 쿼리를 영상 URL에 추가했다.

## 7. 데모 데이터 및 설명 재생성 작업

LLM 적용 후 데모 이벤트에 대해 아래 작업을 수행했다.

- 기존 데모 이벤트들의 상황 설명을 로컬 Gemma4 E4B 기준으로 재생성
- 구조화 JSON 응답 기반 문장으로 전환
- 일부 stale `operator_note`가 AI 설명을 가리는 문제를 정리
- API/대시보드 기준으로 14개 데모 이벤트가 LLM 설명을 갖도록 backfill 수행

사용한 백필 경로는 `backfill-scene-descriptions` 명령 기반이다.

## 8. 오버레이 및 배지 관련 보완 작업

LLM이 이벤트 주체를 정확히 보도록 하려면 오버레이 품질이 중요해서, 아래 보완을 함께 진행했다.

### 8-1. 이벤트 배지 일관화

- 실신/배회 모두 동일한 `AI EVENT` 스타일 배지를 사용하도록 정리
- 이벤트 대상 객체에 강조 박스가 확실히 보이도록 조정

### 8-2. 한글 배지 렌더링 수정

OpenCV 기본 텍스트 렌더링으로는 `배회 의심`, `실신 의심`이 `??????`로 표시되는 문제가 있었다.  
이를 해결하기 위해 `backend/app/visualization/overlay_renderer.py`에서 배지 텍스트 렌더링을 Pillow + 한글 지원 시스템 폰트 기반으로 변경했다.

적용한 폰트 후보 예시는 다음과 같다.

- `AppleSDGothicNeo`
- `AppleGothic`
- `Arial Unicode`
- `NotoSansCJK`
- `NanumGothic`

### 8-3. 오버레이 영상 재생 문제 복구

오버레이를 다시 쓰는 과정에서 일부 MP4가 브라우저 호환성이 떨어지는 `mp4v` 코덱으로 저장되어 재생되지 않는 문제가 발생했다.  
이에 따라 기존 데모 오버레이 14개를 다시 `H.264(avc1)`로 트랜스코딩했다.

결과적으로 다음 문제를 해결했다.

- 브라우저에서 오버레이 영상이 재생되지 않던 문제
- 한글 배지가 `??????`로 보이던 문제
- 오버레이 수정 후에도 캐시 때문에 이전 영상이 남아 보이던 문제

## 9. 테스트 및 검증

테스트는 다음 범위로 수행했다.

- provider 호출 결과 파싱
- 후처리 및 fallback 전환
- JSONL 재기록
- pending 이벤트 재큐잉
- overlay frame 우선 선택
- bbox 기반 focus crop
- 한글 배지 렌더링
- 프론트 타입/렌더 경로 점검

주요 테스트 파일은 다음과 같다.

- `backend/tests/test_scene_description_service.py`
- `backend/tests/test_overlay_renderer.py`
- `backend/tests/test_fastapi_app.py`
- `backend/tests/test_event_repository.py`

운영 검증 항목은 다음과 같다.

- 서버 기동 시 `pending` 이벤트 자동 재등록
- `/api/events`, `/api/summary`, `/api/stream`에 설명 필드 반영
- 오버레이 프레임 기반 LLM 입력 생성
- 데모 이벤트 재생 및 메모 영역 표시 확인

## 10. 현재 운영 상태

현재 기준으로 확보된 상태는 다음과 같다.

- 로컬 Gemma4 E4B를 통한 상황 설명 생성 가능
- FastAPI에서 설명 큐가 자동으로 동작
- 대시보드에서 AI 초안을 메모 영역에서 바로 검토 가능
- 이벤트 주체를 오버레이 배지 기준으로 우선 인식하도록 입력 이미지 보정 적용
- 데모 오버레이 영상의 한글 배지 및 웹 재생 호환성 복구 완료

## 11. 실행 예시

백엔드 실행 예시는 다음과 같다.

```bash
.venv/bin/python -m backend.app.main serve-fastapi \
  --host 127.0.0.1 \
  --port 8100 \
  --enable-scene-description \
  --scene-llm-model gemma4:e4b \
  --scene-llm-host http://127.0.0.1:11434 \
  --scene-llm-timeout 60 \
  --scene-llm-keep-alive 10m
```

기존 이벤트 설명 재생성 예시는 다음과 같다.

```bash
.venv/bin/python -m backend.app.main backfill-scene-descriptions \
  --event-file artifacts/events/dashboard_samples.jsonl \
  --event-file artifacts/events/dashboard_wandering_samples.jsonl \
  --event-file artifacts/events/demo_mobile_check_events.jsonl \
  --scene-llm-model gemma4:e4b \
  --scene-llm-host http://127.0.0.1:11434 \
  --overwrite-completed
```

## 12. 후속 작업 후보

- 실제 운영 데이터 기준으로 프롬프트/출력 슬롯 정밀도 추가 튜닝
- `operator_note` 저장 UX에 “AI 초안 원문” 보존 정책을 둘지 재검토
- 외부 API fallback provider를 붙일지 여부 검토
- 설명 품질 평가용 샘플셋과 정량 비교 기준 문서화
- 배회/실신 외 추가 이벤트 유형으로 슬롯 체계 확장

## 13. 요약

이번 작업으로 “탐지 이벤트 -> 오버레이 기반 대표 프레임 선택 -> 로컬 Gemma4 E4B 호출 -> 구조화 JSON 검증 -> 관제용 한국어 설명 저장 -> 대시보드 메모 영역 반영”까지의 전체 파이프라인이 동작하는 상태가 되었다.  
단순 문장 생성 수준이 아니라, 이벤트 주체 정렬, 구조화 출력, fallback, 재큐잉, 데모 백필, 오버레이 시각화 복구까지 포함한 운영 가능한 형태로 정리한 것이 핵심이다.
