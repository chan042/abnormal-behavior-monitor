# 배회 감지 기능 논문용 엔지니어링 정리

작성일: 2026-04-11

## 1. 문서 목적

이 문서는 논문 본문, 부록, 시스템 구현 섹션, 또는 실험 설정 섹션에 반영할 수 있도록 배회 감지 기능의 엔지니어링 내용을 정제해서 정리한 문서다.  
코드 저장소 중심의 서술보다, 연구 문서에 맞는 형태로 설계 의도, 시스템 구성, 규칙 정의, 최적화 포인트, 실험 프로토콜, 한계 사항을 기술한다.

## 2. 시스템 개요

배회 감지는 학습 기반 행동 분류기가 아니라, `사람 추적 결과 + 전체 영상 영역(full-frame) 기본의 시간 누적 규칙`을 조합한 온라인 규칙 기반 이상행동 탐지기로 구현하였다. 필요할 경우 선택적 ROI를 함께 적용할 수 있지만, 현재 기본 동작은 카메라 전체 프레임을 탐지 영역으로 사용하는 방식이다.

전체 파이프라인은 다음과 같다.

1. 영상 입력에서 사람 객체를 검출 및 추적
2. 각 프레임마다 사람 위치를 기본 탐지 영역인 full-frame 또는 선택적 ROI와 매칭
3. 해당 탐지 영역 내부에서의 궤적 이력을 sliding window로 유지
4. 시간 누적 metric을 계산
5. 규칙을 만족할 때 `wandering_suspected` 이벤트 발생
6. 이벤트 로그, clip, snapshot, overlay를 함께 저장

이 구조는 다음 이유에서 선택되었다.

- 실시간 관제에서 낮은 지연으로 동작 가능
- 행동 분류 모델 없이도 해석 가능한 근거 제공 가능
- 카메라별 threshold 조정만으로 기본 운영이 가능하고, 필요 시 ROI를 추가해 현장 튜닝 가능
- 운영자가 이벤트 근거를 직접 확인할 수 있음

## 3. 온라인 탐지 모델

### 3.1 입력 표현

배회 감지는 객체 추적기의 bbox를 직접 사용한다.  
위치 표현은 bbox 중심점이 아니라 `bottom-center`를 사용하였다.

선택 이유:

- 사람의 실제 이동은 바닥면 기준으로 해석하는 편이 안정적임
- bbox 중심은 상체 자세 변화나 프레임 크기 변화에 영향을 더 받음
- 하단 중심은 복도형 장면에서 보행 위치를 근사하는 데 유리함

### 3.2 Full-Frame 기본 상태 관리

각 추적 id에 대해 다음 상태를 관리한다.

- `IDLE`
- `OBSERVING`
- `WANDERING_SUSPECTED`
- `COOLDOWN`

현재 구현은 ROI 설정이 없을 때 `full_frame` ROI를 자동 생성하여 카메라 전체 화면을 탐지 영역으로 사용한다. 선택적 ROI를 지정한 경우에는 동일한 상태머신으로 해당 구역 내부에서만 metric을 누적한다.  
또한 선택적 ROI 파일에는 `axis: x|y`를 명시할 수 있게 하여 복도 주행 방향을 수동 지정할 수 있도록 설계하였다.

### 3.3 Sliding Window

장시간 누적 이력을 그대로 쓰면 과거 이동이 현재 판정에 과도하게 영향을 주므로, 최근 `window_seconds` 구간만 남기는 sliding window를 사용하였다.

장점:

- 메모리 사용량 제한
- 오래된 이동 이력에 의한 잔상 제거
- 현재 행동 상태에 더 민감하게 반응

## 4. 규칙 기반 metric 설계

배회 감지는 다음 metric들의 조합으로 판단한다.

- `dwell_seconds`: 전체 영상 영역 또는 선택된 ROI 내부 체류 시간
- `direction_changes`: 주 이동축 기준 진행 방향 반전 횟수
- `round_trips`: 방향 반전의 절반 값으로 정의한 왕복 횟수
- `path_ratio`: 총 이동거리 / 순이동거리
- `total_distance_pixels`: sliding window 내 총 이동거리
- `displacement_pixels`: sliding window 시작점과 종료점 사이의 거리
- `axis_excursion_pixels`: 주 이동축 기준 최대 위치 범위
- `idle_ratio`: 작은 움직임 비율
- `window_span_seconds`: 현재 sliding window가 덮는 시간 길이

이 metric 조합은 다음 행동들을 분리하기 위해 설계되었다.

- 직진 통과: `direction_changes`와 `path_ratio`가 낮음
- 장시간 정지: `total_distance_pixels`가 낮고 `idle_ratio`가 높음
- 경계 jitter: `axis_excursion_pixels`가 작음
- 반복 배회: `round_trips`, `direction_changes`, `path_ratio`, `dwell_seconds`가 높음

## 5. 실시간 운영을 위한 엔지니어링 개선

### 5.1 Track Gap 보정

실제 CCTV 환경에서는 tracker가 동일 인물에 대해 일시적으로 새로운 track id를 부여하는 경우가 잦다.  
이를 완화하기 위해 다음 두 가지를 구현하였다.

- `max_track_gap_seconds`: 짧은 추적 공백은 같은 episode로 간주
- `max_relink_distance_pixels`: 가까운 거리에서 재등장한 새 track를 기존 episode에 relink

이 보정이 없으면 배회처럼 장시간 관찰이 필요한 이벤트는 track fragmentation 때문에 쉽게 누락된다.

### 5.2 Idle Ratio 완화

초기 구현에서는 프레임 단위 작은 움직임을 모두 idle로 계산하여, 느린 왕복 배회도 과도하게 억제되는 문제가 있었다.  
이를 완화하기 위해 idle 판정용 step threshold를 별도로 낮춰 작은 보행 움직임은 movement로 흡수되도록 조정하였다.

### 5.3 Axis Excursion 필터

일부 장면에서는 tracker jitter만으로도 방향 전환 수가 비정상적으로 증가하는 문제가 있었다.  
이를 해결하기 위해 `axis_excursion_pixels`를 도입하였다.

의미:

- 실제 배회는 주 이동축에서 일정 범위 이상 왕복해야 함
- jitter는 방향 반전 수가 많아도 실제 공간 점유 폭은 작음

효과:

- 재현율을 크게 해치지 않으면서 일부 jitter성 FP 감소

### 5.4 Event Details 저장

운영자와 연구자가 판정 근거를 직접 검토할 수 있도록, 이벤트 레코드의 `details`에 metric을 함께 저장하였다.

이점:

- 오탐/미탐 분석이 빠름
- threshold 조정 근거 확보
- 연구 문서에서 정량적 기준 제시 가능

## 6. 데이터셋 기반 평가 프로토콜

### 6.1 데이터셋 특성

`wander_sample_1`은 이벤트 시각과 행동 구간이 XML로 주어진 video-level annotation 데이터셋이다.  
정밀 trajectory GT는 없으므로, evaluation target은 `event-level detection`으로 정의하였다.

데이터셋 구성:

- 총 `20`개 비디오
- `3`개 장소(`place01`, `place02`, `place03`)
- 장소별 복수 카메라
- `spring`, `summer` 계절 분포 포함

### 6.2 Segment 정의

평가 manifest는 각 비디오를 다음 세그먼트로 분해한다.

- `wandering_event_full`
- `normal_pre_event`
- `normal_post_event`

이 구조는 positive/negative를 동시에 확보하기 위한 목적이다.

### 6.3 평가 지표

사용 지표:

- `precision`
- `recall`
- `false_positives_per_minute`
- `average_detection_delay_ms`
- `by_place`
- `by_camera`
- `by_profile`

판정 방식:

- positive segment에서 허용 윈도우 내 탐지 발생 시 TP
- negative segment에서 탐지 발생 시 FP

### 6.4 리뷰 아티팩트

정량 결과만으로는 문제 원인을 파악하기 어려우므로, 평가 후 TP/FP overlay를 자동 생성하도록 하였다.

생성 항목:

- overlay mp4
- replay event log
- review manifest

이 구조는 연구 단계에서 qualitative inspection과 quantitative evaluation을 연결한다.

## 7. 성능 변화 요약

샘플 데이터 기준으로 배회 엔진은 다음과 같이 개선되었다.

### 초기 baseline

- `TP 3 / FN 17 / FP 0 / TN 19`
- `precision 1.0`
- `recall 0.15`

특징:

- 매우 보수적
- 재현율이 실사용 수준에 미치지 못함

### 엔진 개선 + threshold tuning 후

- `TP 19 / FN 1 / FP 10 / TN 9`
- `precision 0.655`
- `recall 0.95`

특징:

- 재현율 확보
- 다만 place02 중심의 FP 증가

### axis excursion 필터 후

- `TP 19 / FN 1 / FP 7 / TN 12`
- `precision 0.731`
- `recall 0.95`

의미:

- 재현율 유지
- jitter성 오탐 일부 감소

## 8. 실시간 관제 적용성

본 연구에서 구현한 배회 감지 엔진은 evaluation 전용 모듈이 아니라, 실시간 관제 파이프라인과 동일한 엔진을 사용한다.

즉, 다음은 연구용이면서 동시에 운영용이다.

- 상태머신
- metric 계산
- gap/relink 처리
- cooldown 처리
- axis excursion 필터
- event details 저장

반면 다음은 평가 편의를 위한 연구용 인프라에 가깝다.

- dataset manifest builder
- batch evaluation CLI
- review overlay builder
- sample 전용 ROI/threshold profile

따라서 본 구현은 `실시간 적용 가능한 엔진`을 중심으로 하고, `평가 파이프라인`은 그 엔진을 체계적으로 검증하기 위한 부속 구조라고 설명할 수 있다.

## 9. 엔지니어링 기여 포인트

논문에서 엔지니어링 관점의 기여를 정리하면 다음과 같다.

1. 학습 기반 모델 없이도 실시간 CCTV 배회 감지를 위한 온라인 규칙 엔진을 설계하였다.
2. bbox 중심 대신 bottom-center anchor를 사용하여 보행 위치 해석을 안정화하였다.
3. track fragmentation 완화를 위해 gap/relink 기반 episode 복원 전략을 적용하였다.
4. direction/path/dwell/idle/excursion을 결합한 해석 가능한 rule metric 체계를 구성하였다.
5. 정량 평가와 overlay review를 결합한 검증 루프를 구현하였다.
6. profile 기반 threshold 구조를 중심으로 카메라별 튜닝 가능성을 확보했고, 필요 시 ROI를 추가 적용할 수 있도록 설계하였다.

## 10. 한계와 남은 과제

현재 한계:

- threshold가 장면 종속적임
- 일부 normal pre/post 구간은 annotation 경계와 실제 행위 경계가 어긋날 가능성 존재
- place02처럼 tracker jitter가 심한 장면에서는 여전히 FP가 남음
- 다중 인물 복잡 장면 일반화는 아직 충분히 검증되지 않음

향후 과제:

- 실제 운영 카메라 기준 threshold 재튜닝, 필요 시 선택적 ROI 재설정
- shadow mode 기반 현장 로그 수집
- annotation boundary 보정 또는 weak label 처리
- axis excursion 외의 추가 안정화 metric 탐색
- 필요 시 lightweight learning-based rescoring 도입 검토

## 11. 논문 서술용 예시 문장

### 구현 개요

본 시스템은 사람 객체 추적 결과와 전체 영상 영역(full-frame) 기본의 시간 누적 규칙을 결합하여 배회 행동을 탐지한다. 각 추적 객체에 대해 전체 화면 또는 선택된 ROI 내부 체류 시간, 방향 전환 수, 왕복 횟수, 총 이동거리 대비 순이동거리 비율, 축 방향 이동 범위 등을 sliding window 상에서 계산하고, 사전에 정의한 임계치를 만족할 때 배회 이벤트를 발생시킨다.

### 실시간성

제안 방식은 프레임 단위 추적 결과만을 입력으로 사용하므로 별도 행동 분류 신경망이 필요하지 않으며, 실시간 관제 환경에서 낮은 지연으로 동작 가능하다. 또한 이벤트마다 해석 가능한 metric을 함께 기록하므로, 운영자가 판정 근거를 직접 검토할 수 있다.

### 강건성 보정

실제 CCTV 환경에서 동일 인물의 track id가 단절되는 문제를 완화하기 위해, 시간 간격과 공간 거리 기반 relink 전략을 도입하였다. 또한 tracker jitter에 의해 방향 전환 수가 과대 계산되는 현상을 줄이기 위해 축 방향 이동 범위 기준을 추가하였다.

### 실험 결과 서술 예시

초기 baseline은 높은 precision을 보였으나 recall이 낮았다. 이후 gap/relink 보정, idle 계산 완화, profile 기반 threshold 조정, axis excursion 필터를 순차적으로 도입하여 recall을 크게 향상시켰고, 이후 jitter성 false positive를 감소시키는 방향으로 정밀도를 개선하였다.
