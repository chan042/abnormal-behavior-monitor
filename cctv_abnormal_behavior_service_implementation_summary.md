# CCTV 이상행동 탐지 구현 요약

## 1. 문서 목적
본 문서는 `cctv_abnormal_behavior_service_implementation_history.md`의 핵심만 압축한 요약 문서이다.

현재 프로젝트가 어디까지 구현되었고, 어떤 수준으로 검증되었으며, 다음에 무엇을 해야 하는지를 빠르게 파악하는 데 목적이 있다.

---

## 2. 현재 구현 구조

현재 MVP 구조는 아래와 같다.

1. CCTV 영상 파일 또는 RTSP 입력
2. `YOLO track`으로 사람 검출 및 추적
3. `MediaPipe Pose Landmarker`로 사람별 자세 추출
4. 규칙 기반 실신 엔진으로 `fall_suspected` 판정
5. ROI 및 이동 이력 기반 배회 엔진으로 `wandering_suspected` 판정
6. 이벤트 JSON, clip, snapshot, overlay 저장
7. 최소 관제 대시보드에서 이벤트 확인

즉, 현재는 `모델 학습형`이 아니라 `검출 + 추적 + pose + 규칙 엔진` 기반 MVP가 구현된 상태다.

---

## 3. 완료된 주요 구현

다음 항목은 실제로 구현 완료되었다.

- 프로젝트 골격 생성
  - `backend/`, `configs/`, `data/`, `artifacts/`
- 입력 파이프라인
  - 영상 파일 입력
  - RTSP 입력
  - FPS 샘플링
- 검출 및 추적
  - `YOLO track`
  - `track_id`, `bbox`, `timestamp_ms` 로그 저장
- 자세 추정
  - `MediaPipe Pose Landmarker`
  - pose landmark 로그 저장
- 실신 규칙 엔진
  - 상태 머신 기반 판정
  - threshold/profile 기반 조정 가능
- 배회 규칙 엔진
  - ROI 체류시간, 왕복, 방향 전환 기반 판정
- 이벤트 산출물
  - 이벤트 JSONL
  - clip
  - snapshot
  - overlay 영상
- 최소 대시보드
  - 이벤트 목록
  - 클립 재생
  - 상태 변경

---

## 4. 실제 검증 결과

### 4.1 단일 실제 실신 샘플 검증

`fall_real_01.mp4`로 end-to-end 검증을 수행했다.

결과:

- 기본 threshold에서는 이벤트 `0건`
- 샘플 전용 threshold 조정 후 `실신 이벤트 1건` 탐지
- clip, snapshot, overlay, dashboard 재생까지 확인 완료

즉, 실제 영상 하나에 대해서는 현재 파이프라인이 끝까지 동작함을 확인했다.

### 4.2 `swoon_sample_1` 데이터셋 평가

`swoon_sample_1`은 XML 라벨이 포함된 실신 샘플셋이며, 이를 기반으로 평가 파이프라인을 구축했다.

구성:

- `45개 영상 + 45개 XML`
- `90개 평가 segment`
  - `fall_positive`
  - `normal_pre_event`

추가 구현:

- XML 파서
- manifest 생성기
- batch evaluation
- review overlay 생성기

---

## 5. 현재 기준 성능 요약

현재 가장 현실적인 운영점은 `profiled_v2` 설정이다.

기준 파일:

- `configs/thresholds/fall_swoon_profiled.yaml`
- `artifacts/evaluations/swoon_threshold_profiled_summary.json`

현재 요약:

| 설정 | TP | FN | FP | TN | precision | recall | FPR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `unprofiled_v2_current` | 15 | 30 | 5 | 40 | 0.750 | 0.333 | 0.111 |
| `profiled_v2` | 14 | 31 | 1 | 44 | 0.933 | 0.311 | 0.022 |

해석:

- profile 기반 threshold를 적용하면 FP를 크게 줄일 수 있음
- precision은 높아졌고, recall은 소폭 낮아짐
- 현재는 `정밀도 우선` MVP 운영점으로 보는 것이 적절함

남은 잔여 FP:

- `101-4_cam03_swoon01_place03_day_summer_normal_pre_event`

이 케이스는 현재 `bbox + pose + 규칙` 구조만으로는 완전 제거가 어렵다는 결론에 도달했다.

---

## 6. 현재 판단

현재 상태에 대한 판단은 다음과 같다.

- MVP 구조 구현은 완료됐다.
- 단일 실제 실신 샘플에서는 end-to-end 동작을 확인했다.
- 실신 평가셋 기반 자동 평가와 튜닝 도구까지 구축됐다.
- 샘플셋에 과도하게 맞춘 장면 특화 후처리는 신중해야 한다.
- 지금은 샘플셋 점수 추가 미세조정보다 `현장과 유사한 실제 CCTV 영상으로 일반화 검증`하는 단계가 더 중요하다.

---

## 7. 다음 우선순위

권장 다음 작업은 아래 순서다.

1. 병원·노인시설과 유사한 실제 CCTV 영상 추가 확보
2. 현재 `profiled_v2` 규칙으로 동일한 batch evaluation 수행
3. 현장별 threshold 운영 전략 정리
4. 필요 시 ROI 기반 후처리 또는 운영자 확인 워크플로우 추가

---

## 한 문장 요약

**현재 프로젝트는 `YOLO track + MediaPipe Pose + 실신/배회 규칙 엔진 + 이벤트 저장 + 대시보드 + 평가/튜닝 도구`까지 구현된 실행 가능한 MVP이며, 다음 단계는 실제 현장과 유사한 CCTV 영상으로 일반화 성능을 검증하는 것이다.**
