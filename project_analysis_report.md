# 시니어 실신/배회 탐지 관제 시스템 프로젝트 보고서

## 1. 프로젝트 개요

이 프로젝트는 노인요양시설, 요양병원, 병동, 복지시설과 같이 안전사고의 초기 대응이 중요한 공간을 대상으로 하는 지능형 CCTV 관제 보조 서비스다. 실제 현장에서 발생 빈도가 높은 `실신`과 `배회`탐지를 목표로 한다.

기존에는 사람이 CCTV를 계속 주시해야 해서 관제 피로도가 높고, 야간이나 인력 공백 시간대에 이상상황을 즉시 인지하기 어려웠다. 때문에 고령자·환자의 급작스러운 실신과 보호 대상자의 배회를 놓칠 수 있으며, 사후 영상 확인에 시간이 걸려 초기 대응이 늦어지는 문제가 있었다.

이 프로젝트의 목표는 “실신 및 배회 상황을 빠르게 탐지 후, 멀티 모달 기술을 활용한 상황 설명을 통해 담당자가 빠르게 확인하고 대응할 수 있도록 돕는 관제 시스템”을 만드는 것이다. 현재 구현은 `사람 검출/추적 + 자세 추정 + 규칙 기반 이벤트 엔진` 구조를 택해, 실시간성·해석 가능성·현장 튜닝 용이성을 고려한 형태다.

## 2. 주요 기능

현재 저장소 기준으로 확인되는 주요 기능은 다음과 같다.

- CCTV 영상 파일 입력 처리
- RTSP 스트림 입력 처리
- 로컬 카메라 기반 실시간 모니터링
- 브라우저 카메라 프레임 업로드 기반 실시간 추론
- `YOLO track` 기반 사람 검출 및 추적
- `MediaPipe Pose Landmarker` 기반 사람 자세 추정
- 규칙 기반 실신 감지
- ROI와 이동 이력 기반 배회 감지
- 이벤트 JSONL 저장
- 이벤트 클립, 스냅샷, 오버레이 영상 생성
- 로컬 LLM 기반 상황 설명 생성
- FastAPI 기반 관제 API 제공
- Next.js 기반 관제 대시보드 제공
- 이벤트 상태 변경 기능(미확인/정탐/오탐/종료)
- AI 초안 기반 운영자 메모 저장
- 실신/배회 평가용 데이터셋 manifest 생성
- 배치 평가, 성능 요약, 리뷰용 overlay 생성
- 카메라별 threshold profile 및 ROI profile 튜닝

대시보드는 `실시간 관제`, `이벤트 검토`, `통계/분석`, `설정` 화면을 중심으로 구성되어 있으며, API는 이벤트 목록/상세/클립/스냅샷/상태 변경, 실시간 카메라 상태, 브라우저 라이브 세션 등을 제공한다.

## 3. 실신 감지 알고리즘

실신 감지는 `YOLO 추적 결과 + MediaPipe Pose`를 함께 사용하는 규칙 기반 상태머신으로 구현되어 있다.

### 처리 흐름

1. `YOLO track`으로 사람 bbox와 `track_id`를 얻는다.
2. 각 사람 bbox를 조금 확장해 crop한 뒤 `MediaPipe Pose Landmarker`로 landmark를 추출한다.
3. 프레임별로 다음 지표를 계산한다.
   - 사람 bbox 중심의 세로 하강량
   - bbox 가로/세로 비율 변화
   - 어깨 중심과 엉덩이 중심을 이용한 torso angle 변화
   - landmark 평균 이동량
4. 최근 `fall_window_seconds` 구간의 이력을 기준으로 급격한 자세 붕괴를 탐지한다.
5. 이후 일정 시간 `low motion` 상태가 이어지면 실신 의심 이벤트를 확정한다.

### 상태머신

코드 기준 상태는 아래 흐름으로 동작한다.

- `NORMAL`
- `FALL_SUSPECTED`
- `LYING_OR_COLLAPSED`
- `FALL_CONFIRMED`
- `RECOVERED`

즉, 단순히 넘어지는 순간만 보는 것이 아니라, `급하강/자세변화`와 `이후 무동작 지속`을 함께 만족해야 이벤트가 발생한다.

### 상태 전이 상세

- `NORMAL`
  - 평상시 상태다.
- `FALL_SUSPECTED`
  - 최근 `fall_window_seconds` 구간 안에서 `center_drop`, `angle_change`, `horizontal pose` 조건이 급격하게 나타나면 진입한다.
- `LYING_OR_COLLAPSED`
  - 사람이 실제로 수평에 가까운 자세로 유지되고, 쓰러진 상태가 순간적인 흔들림이 아니라는 것이 확인되면 진입한다.
- `FALL_CONFIRMED`
  - 쓰러진 뒤 `no_motion_seconds` 동안 거의 움직이지 않으면 이벤트를 발생시킨다.
- `RECOVERED`
  - 다시 기립 자세로 돌아오면 복귀 상태로 본다.

즉, 엔진은 `의심 -> 쓰러짐 지속 -> 무동작 확인 -> 이벤트 발생` 순서로 판정한다.

### 핵심 판정 요소

- `center_drop_pixels`: bbox 중심의 급격한 하강
- `center_drop_height_ratio`: 작은 인물도 잡기 위한 정규화 하강 비율
- `angle_change_degrees`: 몸축 각도 변화량
- `horizontal_ratio_threshold`: bbox가 세로형에서 가로형으로 바뀌는지 여부
- `horizontal_angle_threshold`: torso가 수평에 가까워졌는지 여부
- `no_motion_seconds`: 쓰러진 뒤 거의 움직이지 않는 시간이 얼마나 지속되는지
- `max_motion_pixels`: landmark 평균 이동량 기준
- `cooldown_seconds`: 중복 이벤트 방지

또한 threshold YAML에 `profiles`를 두어 카메라별로 민감도를 다르게 조정할 수 있게 되어 있다. 이는 실제 장면별 시야각, 인물 크기, 계절/조도 차이 대응을 위한 구조다.

### 실제 이벤트 발생 조건 예시

현재 기본 운영 설정(`configs/thresholds/fall.yaml`) 기준으로는 대략 다음 순서로 이벤트가 발생한다.

1. 최근 `1초` 이내에 bbox 중심이 `80px` 이상 아래로 떨어지거나,
2. 같은 구간에서 torso 각도가 `45도` 이상 변하거나, bbox가 가로형 비율(`1.2` 이상) 또는 수평 각도(`60도` 이상)에 가까워진다.
3. 사람이 쓰러진 자세로 판단된 뒤, 평균 landmark 움직임이 `12px` 이하인 상태가 `4초` 이상 이어진다.
4. 그러면 `fall_suspected` 이벤트가 발생한다.
5. 이벤트 발생 후에는 `30초` 동안 같은 track에서 중복 이벤트를 막는다.

즉, 기본값만 놓고 보면 “1초 안의 급격한 붕괴 + 4초 이상의 무동작”이 핵심이다.

샘플 데이터셋 튜닝 설정(`fall_swoon_profiled.yaml`)은 더 민감하게 동작한다.

- 붕괴 판단 구간: 최근 `1초`
- 급하강 기준: `20px` 또는 bbox 높이의 `25%`
- 각도 변화 기준: `10도`
- 수평 자세 지속 시간: `0.4초`
- 무동작 확인 시간: `0.2초`
- 최대 확인 지연 허용: `25초`

이 설정은 데이터셋용 프로파일이라 기본 운영값보다 훨씬 공격적으로 이벤트를 만든다. 따라서 보고서에서는 기본 운영값과 평가용 튜닝값을 분리해서 이해하는 것이 맞다.

### 신뢰도 산정 방식

실신 이벤트의 `confidence`는 단일 모델 출력이 아니라 아래 요소를 정규화해서 평균낸 값이다.

- 하강량
- 정규화 하강 비율
- 각도 변화량
- 가로형 비율
- 무동작 정도
- pose confidence

즉, 많이 떨어지고, 많이 기울고, 더 수평에 가까우며, 이후 덜 움직이고, pose 품질이 좋을수록 신뢰도가 높아진다.

### 현재 수준 평가

- 실제 `fall_real_01.mp4`에 대해 end-to-end 탐지와 클립/스냅샷/오버레이/대시보드 확인까지 완료되어 있다.
- `swoon_sample_1` 평가셋 기준 `profiled_v2` 결과는 `precision 0.933`, `recall 0.311`, `false_positive_rate 0.022`다.

즉, 현재 실신 엔진은 `정밀도 우선` 성향의 MVP다. 오탐은 많이 줄였지만 재현율은 아직 낮아, 실제 운영 전에는 더 많은 현장 영상으로 일반화 검증이 필요하다.

## 4. 배회 감지 알고리즘

배회 감지는 자세 정보 없이 `사람 추적 결과 + 전체 영상 영역(full-frame) 또는 선택적 ROI + 시간 누적 규칙`으로 동작하는 온라인 규칙 기반 엔진이다. 현재 코드 기준 기본 동작은 수동 ROI 없이 카메라 전체 프레임을 탐지 영역으로 사용하는 방식이다.

### 처리 흐름

1. 추적 결과에서 사람의 위치를 얻는다.
2. 위치 표현은 bbox 중심이 아니라 `bottom-center`를 사용한다.
3. 사람이 기본 탐지 영역인 전체 영상 영역(`full_frame`) 또는 선택적으로 지정된 ROI 내부에 들어오면 해당 `track_id`에 대한 episode를 시작한다.
4. 최근 `window_seconds` 구간의 위치 이력을 유지한다.
5. 체류 시간, 이동 방향 변화, 왕복 횟수, 이동거리 대비 순이동거리 비율 등을 계산한다.
6. 임계치를 넘으면 `wandering_suspected` 이벤트를 발생시킨다.

### 상태 관리

코드 기준 상태는 다음과 같다.

- `IDLE`
- `OBSERVING`
- `WANDERING_SUSPECTED`
- `COOLDOWN`

기본 full-frame 모드에서는 사실상 카메라 전체가 관심영역이므로 별도 구역 이탈 개념이 약하다. 다만 엔진 내부는 ROI 추상화를 유지하고 있어, 선택적 ROI를 지정한 경우에는 ROI 밖에 오래 머무르면 episode를 종료하고, 일정 시간 이내 가까운 위치에서 새 `track_id`가 나타나면 기존 episode와 relink하는 보정도 포함되어 있다.

### 상태 전이 상세

- `IDLE`
  - 아직 추적 이력이 없거나 episode가 초기화된 상태다.
- `OBSERVING`
  - 사람이 full-frame 또는 선택적 ROI 안에서 계속 관찰되고 있으며 metric을 누적하는 상태다.
- `WANDERING_SUSPECTED`
  - 체류 시간, 방향 전환, 왕복, path ratio, 이동거리 등이 모두 임계치를 넘으면 이벤트를 발생시키며 진입한다.
- `COOLDOWN`
  - 이벤트 직후 같은 패턴으로 연속 알림이 발생하지 않도록 잠시 중복 억제를 거는 상태다.

추적이 잠깐 끊겨도 바로 리셋하지 않고, `max_track_gap_seconds`와 `max_relink_distance_pixels`를 이용해 같은 사람의 episode를 이어붙이도록 만든 점이 특징이다.

### 핵심 metric

- `dwell_seconds`: 전체 영상 영역 또는 선택된 ROI 내부 체류 시간
- `direction_changes`: 주 이동축 기준 방향 반전 횟수
- `round_trips`: 왕복 횟수
- `path_ratio`: 총 이동거리 / 순이동거리
- `total_distance_pixels`: 누적 이동거리
- `displacement_pixels`: 시작점과 끝점 사이 거리
- `axis_excursion_pixels`: 주 이동축 기준 최대 이동 범위
- `idle_ratio`: 거의 정지 상태였던 비율
- `window_span_seconds`: 현재 sliding window 길이

이 metric 조합으로 아래 행동을 구분하도록 설계되어 있다.

- 단순 통과: 방향 전환과 path ratio가 낮음
- 장시간 정지: 이동거리 부족, idle ratio 높음
- jitter: 방향 전환은 많아 보여도 axis excursion이 작음
- 반복 배회: 체류 시간, 방향 전환, 왕복, path ratio가 모두 높음

### 실제 이벤트 발생 조건 예시

기본 운영 설정(`configs/thresholds/wandering.yaml`) 기준으로는 배회 이벤트가 다음 조건을 동시에 만족해야 발생한다.

1. 최근 `180초` sliding window 안에서 관찰 이력이 누적된다.
2. 체류 시간이 최소 `180초` 이상이어야 한다.
3. 방향 전환이 최소 `5회` 이상이어야 한다.
4. 왕복 횟수는 최소 `3회` 이상이어야 한다.
5. `path_ratio`가 `2.5` 이상이어야 한다.
   - 즉, 실제 이동거리는 길지만 출발점과 도착점은 가깝다는 뜻이다.
6. 누적 이동거리가 최소 `350px` 이상이어야 한다.
7. `idle_ratio`는 `0.7` 이하여야 한다.
   - 오래 머물기만 하고 거의 움직이지 않는 경우는 배회로 보지 않는다.
8. 이벤트 발생 후에는 `120초` cooldown이 걸린다.

즉, 단순히 오래 머무르는 것만으로는 이벤트가 뜨지 않고, `오래 머묾 + 반복 왕복 + 방향 전환 + 제자리 주변 반복 이동`이 동시에 확인되어야 한다.

실시간 데모/모바일용 프로파일(`demo_mobile`, `cam_live_01`)은 더 민감하게 완화되어 있다.

- 체류 시간: `20초`
- 왕복 횟수: `2회`
- 방향 전환: `4회`
- `path_ratio`: `1.8`
- 총 이동거리: `280px`
- 최소 축 이동 폭(`axis_excursion_pixels`): `120px`
- `idle_ratio`: `0.95` 이하

샘플 평가용 설정(`wandering_wander_sample_1.yaml`)은 기본적으로 다음 값으로 시작한다.

- 체류 시간: `30초`
- 왕복 횟수: `2회`
- 방향 전환: `4회`
- `path_ratio`: `2.0`
- 총 이동거리: `500px`
- sliding window: `90초`
- reentry grace: `2초`

그리고 장소/카메라별 profile에서 일부 값을 더 완화한다. 예를 들어 `place01_cam01`은 `왕복 1회`, `방향 전환 3회`, `path_ratio 1.8`, `총 이동거리 360px` 수준까지 낮춰 검출 민감도를 높인다.

### 중복 억제와 track 보정

배회 엔진은 운영 환경에서 중요한 보정 로직도 포함한다.

- `max_track_gap_seconds`
  - 기본값은 `2초`이며, 이보다 오래 추적이 끊기면 episode를 리셋한다.
- `reentry_grace_seconds`
  - ROI 밖으로 잠깐 벗어났다가 `1초` 이내에 다시 들어오면 같은 episode로 유지한다.
- `max_relink_distance_pixels`
  - 기본값은 `220px`이며, 가까운 위치에서 새 track가 나타나면 같은 사람으로 relink할 수 있다.
- 추가 이벤트 발생 조건
  - 첫 이벤트 이후에는 단순 반복 알림을 내지 않고, `왕복 횟수가 더 증가`하거나 `방향 전환이 2회 이상 더 늘어날 때`만 다시 이벤트를 발생시킨다.

### 이벤트 로그와 신뢰도 산정

배회 이벤트가 발생하면 `details`에 아래 값이 함께 저장된다.

- `dwell_seconds`
- `round_trips`
- `direction_changes`
- `path_ratio`
- `total_distance_pixels`
- `displacement_pixels`
- `axis_excursion_pixels`
- `idle_ratio`
- `window_span_seconds`

`confidence`는 체류 시간, 왕복 수, 방향 전환 수, path ratio, 이동거리, 축 이동 폭, 활동성 점수를 정규화해서 평균낸 값이다. 즉, 오래 머물고, 많이 왕복하고, 방향 전환이 많고, 실제 이동 흔적이 뚜렷할수록 신뢰도가 올라간다.

### 배회 엔진의 강점

- 기본은 full-frame으로 바로 동작하고, 필요 시 ROI와 threshold를 카메라별로 조정 가능
- gap/relink 로직으로 tracker 단절에 어느 정도 강건함
- 이벤트 `details`에 근거 metric이 저장되어 운영자와 연구자가 오탐 원인을 해석하기 쉬움

### 현재 수준 평가

- `wander_sample_1` 튜닝 결과는 `precision 0.655`, `recall 0.95`다.
- 이후 `axis excursion` 필터를 적용한 문서 기준 성능은 `precision 0.731`, `recall 0.95`다.
- `place02` 장면처럼 tracker jitter가 큰 구간에서는 여전히 false positive가 남아 있다.

즉, 배회 엔진은 실신 엔진보다 재현율은 높지만 장면 의존성이 더 크고, 현재는 full-frame 기본 전략 위에 필요 시 ROI/threshold 튜닝을 추가하는 방식으로 이해하는 것이 맞다.

## 5. 사용한 기술

### 백엔드

- Python
- FastAPI
- Uvicorn
- OpenCV
- Ultralytics YOLO
- ByteTrack
- MediaPipe Pose Landmarker
- PyYAML
- HTTPX

### 프론트엔드

- Next.js 16
- React 19
- TypeScript
- Tailwind CSS v4
- ESLint

### 데이터 및 운영 방식

- YAML 기반 카메라/ROI/threshold 설정
- JSONL 기반 tracking/pose/event 로그 저장
- XML 라벨 기반 실신/배회 샘플셋 평가
- clip/snapshot/overlay 산출물 자동 생성
- SSE 기반 요약 스트림, MJPEG 기반 라이브 스트림

### 검증 체계

- `backend/tests` 기준 39개 테스트가 존재하며, 현재 환경에서 `OK`로 통과했다.
- 실신/배회 batch evaluation과 review overlay 생성 도구가 분리되어 있어 연구·튜닝 루프가 갖춰져 있다.

## 6. 로컬 LLM 상황 설명 연동 현황

프로젝트 초기 목표 중 하나였던 “탐지 후 상황 설명 자동 생성” 기능은 이번 작업을 통해 실제 동작하는 형태로 연결되었다. 현재 구조는 `백엔드 -> 로컬 HTTP 추론 서버(Ollama 호환)` 방식이며, 우선 적용 모델은 `Gemma 4 E4B`다. 보안성과 운영 독립성을 고려해 외부 API보다 로컬 모델을 우선 채택했고, 향후 필요 시 provider 계층만 교체해 외부 API fallback을 붙일 수 있게 분리해 두었다.

### 연동 방식

- 이벤트는 기존처럼 즉시 저장하고 대시보드에 바로 반영한다.
- 상황 설명은 별도 비동기 worker가 후처리한다.
- 설명 생성 실패 시 탐지 파이프라인은 멈추지 않고 기존 규칙 기반 문구를 유지한다.
- FastAPI 재시작 시 `description_status=pending` 이벤트를 다시 스캔해 재큐잉한다.

즉, 실시간 탐지와 설명 생성을 분리해 탐지 지연을 최소화하는 구조다.

### 백엔드 구현 내용

상황 설명 전용 서비스 계층이 추가되었고, 이벤트 저장 경로와 FastAPI, 라이브 모니터, 브라우저 라이브 경로가 동일한 큐를 사용하도록 통합되었다.

- `SceneDescriptionService` 단일 worker 큐 추가
- `OllamaSceneDescriptionProvider`를 통한 로컬 모델 HTTP 호출 구현
- CLI/FastAPI 실행 옵션 추가
  - `--enable-scene-description`
  - `--scene-llm-model`
  - `--scene-llm-host`
  - `--scene-llm-timeout`
  - `--scene-llm-keep-alive`
- 이벤트 스키마에 설명 상태 추적 필드 추가
  - `updated_at`
  - `description_status`
  - `description_source`
  - `description_generated_at`
  - `description_error`
  - `operator_note`

`description_status`는 `pending | completed | failed | fallback` 네 가지 상태를 사용한다.

### 프롬프트 엔지니어링과 구조화 출력

초기에는 단문 설명 생성만 목표였지만, 실제 적용 과정에서 복장/연령/성별 누락과 장면 전반 오해석이 발생해 구조화 JSON 출력 방식으로 강화했다. 현재는 LLM이 아래 키를 반드시 포함한 JSON 객체 하나만 반환하도록 강제한다.

- `age_group`
- `gender`
- `upper_clothing`
- `lower_clothing`
- `action_posture`
- `location`
- `event_phrase`

후처리 단계에서는 허용값 정규화, UI 표현 제거, 필수 슬롯 검증, 길이 제한 검증을 수행한 뒤 최종 한국어 문장으로 재조합한다. 이 방식으로 “연령대, 성별, 상의, 하의”를 포함한 설명을 일관되게 만들도록 보완했다.

### 이벤트 주체 정렬 방식

배회 이벤트처럼 프레임 안에 여러 사람이 보일 수 있는 경우, LLM이 이벤트 대상이 아닌 다른 사람까지 함께 설명하는 문제가 있었다. 이를 줄이기 위해 단순 snapshot 대신 `오버레이 클립의 이벤트 프레임`을 우선 사용하고, 가능하면 `target_bbox` 기준 crop 이미지를 추가로 만들어 LLM 입력에 사용하도록 수정했다.

프롬프트에도 아래 규칙을 명시했다.

- `AI EVENT` 배지와 강조 박스가 붙은 사람 한 명만 설명
- 배지가 없는 다른 인물은 설명에서 제외
- 배지, 박스, 오버레이 자체는 묘사하지 않음

즉, 현재 설명 생성은 “이벤트가 발생한 객체” 중심으로 정렬되도록 설계되어 있다.

### 프론트엔드 반영

초기에는 별도 AI 설명 영역을 두는 방안도 검토했지만, 최종적으로는 운영자 메모 흐름과 결합하는 쪽이 더 가볍고 실용적이라고 판단했다. 현재 대시보드는 `operator_note`가 있으면 그것을 우선 표시하고, 비어 있으면 AI가 생성한 `description`을 메모 초안처럼 보여준다. 따라서 관제사는 AI 초안을 그대로 읽는 것에서 끝나는 것이 아니라, 메모 영역에서 내용을 수정하거나 보강한 뒤 저장할 수 있다.

또한 이벤트 상세와 미리보기에서는 오버레이 영상을 우선 재생하도록 정리했고, 오버레이 갱신 후에도 브라우저가 이전 MP4를 붙잡지 않도록 `updated_at` 기반 cache-busting 쿼리도 추가했다.

### 데모/오버레이 보완 작업

LLM 적용 과정에서 설명 품질뿐 아니라 오버레이 품질도 함께 보완했다.

- 실신/배회 모두 동일한 이벤트 배지 디자인으로 통일
- 이벤트 대상 객체에 강조 박스를 명확히 적용
- OpenCV 기본 텍스트 렌더링으로 한글이 `??????`로 깨지는 문제를 Pillow + 한글 지원 시스템 폰트 경로로 수정
- 오버레이 영상을 다시 쓰는 과정에서 일부 MP4가 `mp4v`로 저장되어 브라우저 재생이 막히는 문제를 확인하고, 전체 데모 오버레이를 `H.264(avc1)`로 다시 변환
- 프론트는 항상 오버레이 버전을 우선 표시하도록 정리

이 보완 작업은 단순 시각 개선이 아니라, LLM이 이벤트 주체를 더 정확히 보도록 만드는 입력 품질 개선과도 직접 연결된다.

### 현재 수준 평가

현재 기준으로는 “탐지 이벤트 -> 대표 프레임 선택 -> 로컬 Gemma4 E4B 호출 -> 구조화 JSON 검증 -> 관제용 설명 저장 -> 메모 영역 반영”까지의 전체 파이프라인이 동작한다. 즉, 상황 설명 기능은 더 이상 계획 단계가 아니라 실제 데모와 대시보드에서 확인 가능한 구현 단계에 들어왔다.

다만 향후 과제는 여전히 남아 있다.

- 실제 운영 영상 기준 설명 품질의 일반화 검증
- 구조화 슬롯의 세밀한 튜닝
- 외부 API fallback 필요 여부 검토
- 설명 품질 정량 평가 기준 정립

정리하면, 로컬 LLM 연동은 현재 프로젝트에서 “가장 큰 미구현 항목” 수준을 넘어, 기본 동작과 운영 흐름이 갖춰진 기능으로 전환되었다고 평가할 수 있다.

## 7. 목표 대비 완성도

저장소 분석 기준으로 보면, 이 프로젝트는 “실신·배회 탐지 관제 보조 MVP”라는 초기 목표에 대해서는 꽤 높은 완성도에 도달해 있다. 다만 “현장 배포 가능한 상용 서비스” 관점에서는 아직 검증과 고도화가 더 필요하다.

### 종합 판단

- MVP 완성도: 약 `80~85%`
- 현장 실서비스 완성도: 약 `55~65%`

이 수치는 코드, 문서, 테스트, 평가 결과를 바탕으로 한 추정치다.

### 높게 평가할 수 있는 부분

- 실시간 입력부터 이벤트 생성, 아티팩트 저장, 대시보드 확인까지 end-to-end 파이프라인이 연결되어 있음
- 실신과 배회 모두 독립적인 규칙 엔진이 구현되어 있음
- 카메라별 threshold/ROI profile 구조가 이미 도입되어 있음
- 평가용 manifest, batch evaluation, review overlay까지 구축되어 있어 반복 개선 체계가 있음
- 브라우저 카메라 라이브와 FastAPI 대시보드까지 포함해 시연 가능한 수준의 MVP가 완성됨
- 자동 테스트 39개가 통과해 기본 회귀 안정성이 확보됨

### 아직 남은 과제

- 실신 감지는 precision은 높지만 recall이 낮아 실제 누락 위험이 남아 있음
- 배회 감지는 recall은 높지만 장면별 false positive가 존재함
- threshold가 여전히 장면 종속적이며 현장 재튜닝 필요성이 큼
- 실제 병원/요양시설 CCTV 데이터 기반 일반화 검증이 충분하지 않음
- 운영 알림 연동, 사용자 권한, 장기 로그 관리 같은 서비스 운영 기능은 제한적임

정리하면, 이 저장소는 “기획서 수준”을 넘어서 실제로 동작하는 `검증 가능한 MVP`이며, 다음 단계의 핵심은 기능 추가보다 `현장 일반화 성능 검증`과 `운영 안정화`다.

## 8. 기대 효과

이 프로젝트가 실제 현장에 적용되면 다음 효과를 기대할 수 있다.

- 실신 상황을 더 빠르게 포착해 초기 대응 시간을 단축할 수 있음
- 보호가 필요한 환자·입소자의 배회 위험을 조기에 인지할 수 있음
- CCTV를 지속적으로 응시해야 하는 관제 부담을 줄일 수 있음
- 야간, 휴게 시간, 인력 부족 상황에서 보조 감시 수단이 될 수 있음
- 이벤트 중심 검토가 가능해 사후 분석과 보고 업무가 쉬워짐
- 축적된 이벤트 로그와 리뷰 데이터는 향후 threshold 개선이나 학습형 고도화의 기반이 될 수 있음

## 9. 결론

이 프로젝트는 노인시설·병원 환경에 특화된 `실신/배회 탐지 관제 보조 서비스`라는 기획 방향이 코드와 시스템 구조에 비교적 일관되게 반영된 사례다. 현재 수준은 실시간 데모와 성능 실험이 가능한 실행형 MVP로 평가할 수 있으며, 특히 배치 평가와 리뷰 인프라까지 함께 갖춘 점이 강점이다.

다만 정확도 측면에서는 실신은 재현율, 배회는 장면별 오탐이 여전히 핵심 과제로 남아 있다. 따라서 다음 단계는 새로운 기능을 넓히는 것보다, 실제 운영 환경과 유사한 CCTV 데이터로 일반화 성능을 검증하고 카메라별 운영 전략을 정교화하는 데 집중하는 것이 적절하다.

## 10. 분석 근거 파일

- `cctv_abnormal_behavior_service_idea.md`
- `cctv_abnormal_behavior_service_implementation_roadmap.md`
- `cctv_abnormal_behavior_service_implementation_summary.md`
- `backend/app/scene_description/service.py`
- `wandering_detection_engineering_notes_for_paper.md`
- `backend/app/rules/fall.py`
- `backend/app/rules/wandering.py`
- `backend/app/pipeline.py`
- `backend/app/api/fastapi_app.py`
- `backend/app/live/service.py`
- `backend/tests/`
- `artifacts/evaluations/swoon_threshold_profiled_summary.json`
- `artifacts/evaluations/wander_eval_summary_tuned.json`
