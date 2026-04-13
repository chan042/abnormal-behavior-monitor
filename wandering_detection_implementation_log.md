# 배회 감지 기능 구현 기록

작성일: 2026-04-11  
프로젝트: `abnormal-behavior-monitor`

## 1. 문서 목적

이 문서는 현재 저장소에서 배회 감지 기능을 구현하고 고도화하기 위해 수행한 작업을 기술 기록 관점에서 정리한 문서다.  
대상은 다음 두 가지다.

- 실제 코드 변경 이력과 구조적 개선 사항을 추적하려는 개발자
- 배회 감지 기능이 현재 어떤 수준까지 구현되었는지 파악하려는 운영/기획/연구 인원

이 문서는 `무엇을 바꿨는지`, `왜 바꿨는지`, `어떻게 검증했는지`, `현재 상태가 어떤지`를 중심으로 정리한다.

## 2. 구현 목표

배회 감지 기능의 1차 목표는 다음과 같았다.

- 고정 복도형 카메라에서 반복적 왕복 이동을 배회로 감지
- 직진 통과, 장시간 정지, 탐지 영역 경계 jitter를 배회와 구분
- 이벤트 근거 metric을 로그에 남겨 운영자가 판정 이유를 확인 가능하게 구성
- 카메라별 threshold 조정만으로 기본 현장 튜닝이 가능하고, 필요 시 ROI도 함께 적용할 수 있도록 설계
- 배치 평가, 리뷰 overlay, 라이브 집계까지 하나의 파이프라인으로 연결

## 3. 전체 작업 요약

배회 감지 작업은 크게 네 축으로 진행했다.

1. 배회 규칙 엔진 자체 개선
2. 설정/이벤트/라이브 인터페이스 확장
3. `wander_sample_1` 데이터셋 기반 평가 파이프라인 구축
4. 샘플 데이터 기반 재현율/정밀도 튜닝 및 오탐 분석

## 4. 핵심 코드 변경

### 4.1 배회 엔진 고도화

핵심 엔진은 [backend/app/rules/wandering.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/rules/wandering.py) 에 구현되어 있다.

주요 변경 사항:

- `episode + sliding window` 기반 상태 관리로 재구성
- 최근 `window_seconds` 내 위치만 유지하도록 변경해 무한 이력 누적 제거
- `track gap`, `reentry grace`, `cooldown` 로직 추가
- `dwell_seconds`, `direction_changes`, `round_trips`, `path_ratio`, `total_distance_pixels`, `idle_ratio` 기반 규칙 정비
- `details` 필드에 배회 판정 근거 metric 저장
- bbox 중심 대신 `bottom-center` 기반 motion anchor 사용
- tracker가 짧게 끊겼을 때 `track relink`로 episode를 이어붙이도록 개선
- `axis excursion` 기반 최소 왕복 폭 필터 추가

배회 엔진이 현재 사용하는 주요 metric:

- `dwell_seconds`
- `round_trips`
- `direction_changes`
- `path_ratio`
- `total_distance_pixels`
- `displacement_pixels`
- `axis_excursion_pixels`
- `idle_ratio`
- `window_span_seconds`

### 4.2 설정 체계 확장

설정 관련 변경은 다음 파일들에 반영했다.

- [backend/app/config.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/config.py)
- [configs/thresholds/wandering.yaml](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/thresholds/wandering.yaml)
- [configs/thresholds/wandering_wander_sample_1.yaml](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/thresholds/wandering_wander_sample_1.yaml)
- [configs/rois/example_ward_corridor.yaml](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/rois/example_ward_corridor.yaml)
- [configs/rois/wandering/](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/rois/wandering)

추가된 주요 설정:

- `window_seconds`
- `max_track_gap_seconds`
- `reentry_grace_seconds`
- `min_total_distance_pixels`
- `max_idle_ratio`
- `max_relink_distance_pixels`
- `min_axis_excursion_pixels`
- `profiles:` 기반 카메라/장면별 override
- 선택적 ROI `axis`
- 선택적 ROI `event_types`

### 4.3 이벤트 및 라이브 집계 반영

배회 이벤트와 라이브 요약 반영을 위해 다음을 수정했다.

- [backend/app/events/schema.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/events/schema.py)
- [backend/app/api/repository.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/api/repository.py)
- [backend/app/pipeline.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/pipeline.py)
- [backend/app/live/service.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/live/service.py)
- [frontend/src/types/dashboard.ts](/Users/chan/Project/DataServices/abnormal-behavior-monitor/frontend/src/types/dashboard.ts)

반영 내용:

- `EventRecord.details` 저장 및 조회 지원
- 라이브 카메라 요약에 `wandering_events` 반영
- 카메라 설정의 `wandering_threshold_profile`을 엔진에 전달
- 실시간/배치 파이프라인 모두 같은 엔진을 사용하도록 통일

### 4.4 CLI 및 평가 도구 추가

다음 명령을 새로 추가했다.

- `build-wander-manifest`
- `evaluate-wandering-manifest`
- `build-wandering-review`

관련 구현 파일:

- [backend/app/main.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/main.py)
- [backend/app/evaluation/wander_dataset.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/evaluation/wander_dataset.py)
- [backend/app/evaluation/wander_batch.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/evaluation/wander_batch.py)
- [backend/app/evaluation/wander_review.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/evaluation/wander_review.py)

추가로 `main.py`는 lazy import를 적용해서 `fastapi`가 없는 환경에서도 manifest/evaluation 계열 CLI가 실행되도록 조정했다.

## 5. `wander_sample_1` 데이터셋 활용 작업

### 5.1 데이터 파싱 및 manifest 생성

`wander_sample_1`에 대해 XML 파서와 manifest 생성기를 만들었다.

산출물:

- [data/manifests/wander_sample_1_videos.jsonl](/Users/chan/Project/DataServices/abnormal-behavior-monitor/data/manifests/wander_sample_1_videos.jsonl)
- [data/manifests/wander_sample_1_segments.jsonl](/Users/chan/Project/DataServices/abnormal-behavior-monitor/data/manifests/wander_sample_1_segments.jsonl)

생성 결과:

- 비디오 레코드: `20`
- 평가 세그먼트: `39`
- 세그먼트 구성:
  - `wandering_event_full`: `20`
  - `normal_pre_event`: `11`
  - `normal_post_event`: `8`

데이터셋 메타데이터 이슈도 함께 기록했다.

- 폴더명과 take id 불일치
- 파일명 `night` 와 XML `DAY` 불일치

이 경고는 manifest의 `metadata_warnings`에 반영했다.

### 5.2 sample 평가용 ROI/threshold 초기 프로필 작성

`wander_sample_1` 기준으로 다음 초기 프로필을 작성했다.

ROI:

- `place01_cam01`
- `place02_cam01`
- `place02_cam02`
- `place03_cam01`
- `place03_cam02`

Threshold profile:

- [configs/thresholds/wandering_wander_sample_1.yaml](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/thresholds/wandering_wander_sample_1.yaml)

### 5.3 배치 평가 및 리뷰 overlay 생성

생성된 평가 산출물:

- baseline summary: [artifacts/evaluations/wander_eval_summary.json](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/evaluations/wander_eval_summary.json)
- tuned full-run summary: [artifacts/evaluations/wander_eval_summary_tuned.json](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/evaluations/wander_eval_summary_tuned.json)
- axis filter replay summary: [artifacts/evaluations/wander_eval_summary_axis_replay.json](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/evaluations/wander_eval_summary_axis_replay.json)

리뷰 overlay 산출물:

- TP 리뷰: [artifacts/review/wander_candidate_review](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/review/wander_candidate_review)
- FP 리뷰: [artifacts/review/wander_fp_review_axis](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/review/wander_fp_review_axis)

## 6. 테스트 작업

추가/확장된 테스트:

- [backend/tests/test_wandering_rule.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/tests/test_wandering_rule.py)
- [backend/tests/test_wander_dataset.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/tests/test_wander_dataset.py)
- [backend/tests/test_wander_batch.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/tests/test_wander_batch.py)
- [backend/tests/test_wander_review.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/tests/test_wander_review.py)
- [backend/tests/test_live_service.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/tests/test_live_service.py)

검증한 주요 항목:

- 왕복 배회 이벤트 발생
- 직진 통과 미검출
- 장시간 정지 미검출
- 탐지 영역 경계 jitter 미검출
- cooldown 중복 억제
- 짧은 track gap 유지
- track relink 유지
- dataset parser/segment generation
- batch evaluation runner 연결
- review target filtering

주요 실행 명령:

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache .venv/bin/python -m unittest \
  backend.tests.test_wandering_rule \
  backend.tests.test_wander_batch \
  backend.tests.test_wander_dataset \
  backend.tests.test_wander_review \
  backend.tests.test_live_service \
  backend.tests.test_event_repository
```

## 7. 성능 개선 과정

### 7.1 baseline

baseline 성능은 매우 보수적이었다.

- `TP 3 / FN 17 / FP 0 / TN 19`
- `precision 1.0`
- `recall 0.15`

특징:

- 오탐은 거의 없었지만 재현율이 지나치게 낮음
- `place02/cam02`에서만 일부 검출
- `place03` 전체 미검출

### 7.2 1차 튜닝

엔진 개선과 threshold 완화를 적용한 뒤:

- `TP 19 / FN 1 / FP 10 / TN 9`
- `precision 0.655`
- `recall 0.95`

특징:

- 재현율은 크게 향상
- 대신 `place02` normal pre/post에서 FP 증가

### 7.3 axis excursion 필터 추가 후

현재 latest replay 기준:

- `TP 19 / FN 1 / FP 7 / TN 12`
- `precision 0.731`
- `recall 0.95`
- `false_positives_per_minute 0.5363`

해석:

- recall은 유지
- jitter성 오탐 일부 제거
- 남은 FP는 주로 `place02`의 normal pre/post 경계 구간에 집중

## 8. 실시간 관제와의 관계

중요한 점은 이번 작업이 전부 샘플 전용이 아니라는 것이다.

실시간 관제에 직접 반영되는 항목:

- [backend/app/rules/wandering.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/rules/wandering.py) 의 엔진 개선
- [backend/app/pipeline.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/pipeline.py) 의 배회 엔진 연결
- [backend/app/live/service.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/live/service.py) 의 라이브 집계/실행 경로

샘플 데이터 전용 항목:

- `wander_sample_1` manifest
- sample 평가용 ROI profile
- sample 전용 threshold profile
- sample 전용 evaluation/review artifacts

즉, `엔진 개선은 운영에도 반영되지만`, `현재 sample용 threshold 값이 바로 운영 카메라에 최적이라고 단정할 수는 없다`.

## 9. 현재 상태 요약

현재 상태를 한 줄로 정리하면 다음과 같다.

> 배회 감지 기능은 코드상 동작하며, 샘플 데이터 기준으로 높은 재현율까지 확보했고, 남은 과제는 운영 카메라용 threshold 현장 튜닝과 필요 시 선택적 ROI 적용 전략 정리다.

현재 구현 완료 항목:

- 배회 이벤트 엔진
- 세부 metric 로그
- 배치 평가 CLI
- review overlay 생성 CLI
- 라이브 집계 반영
- sample 데이터 기반 검증 루프

현재 미완 항목:

- 실제 운영 카메라별 threshold 재튜닝
- 운영 카메라별 threshold profile 이식
- shadow mode 기반 실시간 오탐/미탐 로그 검증
- 필요 시 운영 카메라별 선택적 ROI 검토

## 10. 다음 권장 작업

다음 우선순위는 다음과 같다.

1. 실제 운영 카메라 1대를 선택
2. 운영 카메라 기준 full-frame으로 shadow mode 검증
3. sample 튜닝 결과를 운영용 [configs/thresholds/wandering.yaml](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/thresholds/wandering.yaml) 에 이식
4. 운영 로그 기준 FP/FN 재튜닝
5. 필요 시에만 운영 카메라 기준 ROI 작성

## 11. 관련 파일 목록

핵심 구현 파일:

- [backend/app/rules/wandering.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/rules/wandering.py)
- [backend/app/pipeline.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/pipeline.py)
- [backend/app/live/service.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/live/service.py)
- [backend/app/events/schema.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/events/schema.py)
- [backend/app/config.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/config.py)
- [backend/app/main.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/main.py)

평가/리뷰 파일:

- [backend/app/evaluation/wander_dataset.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/evaluation/wander_dataset.py)
- [backend/app/evaluation/wander_batch.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/evaluation/wander_batch.py)
- [backend/app/evaluation/wander_review.py](/Users/chan/Project/DataServices/abnormal-behavior-monitor/backend/app/evaluation/wander_review.py)

설정 파일:

- [configs/thresholds/wandering.yaml](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/thresholds/wandering.yaml)
- [configs/thresholds/wandering_wander_sample_1.yaml](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/thresholds/wandering_wander_sample_1.yaml)
- [configs/rois/example_ward_corridor.yaml](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/rois/example_ward_corridor.yaml)
- [configs/rois/wandering](/Users/chan/Project/DataServices/abnormal-behavior-monitor/configs/rois/wandering)

산출물:

- [data/manifests/wander_sample_1_videos.jsonl](/Users/chan/Project/DataServices/abnormal-behavior-monitor/data/manifests/wander_sample_1_videos.jsonl)
- [data/manifests/wander_sample_1_segments.jsonl](/Users/chan/Project/DataServices/abnormal-behavior-monitor/data/manifests/wander_sample_1_segments.jsonl)
- [artifacts/evaluations/wander_eval_summary.json](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/evaluations/wander_eval_summary.json)
- [artifacts/evaluations/wander_eval_summary_tuned.json](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/evaluations/wander_eval_summary_tuned.json)
- [artifacts/evaluations/wander_eval_summary_axis_replay.json](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/evaluations/wander_eval_summary_axis_replay.json)
- [artifacts/review/wander_candidate_review](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/review/wander_candidate_review)
- [artifacts/review/wander_fp_review_axis](/Users/chan/Project/DataServices/abnormal-behavior-monitor/artifacts/review/wander_fp_review_axis)
