# 노인시설·병원 대상 CCTV 이상행동 탐지 구현 로드맵

## 1. 문서 목적
본 문서는 현재 프로젝트의 실제 구현 순서를 정리한 실행 문서이다.

현재 기술 방향은 다음과 같다.

- `YOLO track`으로 사람 검출 및 추적
- `MediaPipe Pose Landmarker`로 자세 추출
- 실신 규칙 엔진으로 실신 판정
- 전체 영상 영역(full-frame) 기본의 이동 이력 기반 규칙 엔진으로 배회 판정

이 문서는 모델 학습 계획이 아니라, 위 구조를 실제 서비스 형태로 만드는 순서를 정의한다.

---

## 2. 현재 기준 문서
- 서비스 방향: `cctv_abnormal_behavior_service_idea.md`
- 실행 기준: 이 문서

---

## 3. 핵심 설계 요약

### 3.1 전체 아키텍처
1. CCTV 영상 또는 RTSP 스트림 입력
2. 프레임 샘플링 및 전처리
3. `YOLO track`으로 사람 검출 및 `track_id` 부여
4. 사람별 crop 또는 bbox 기준으로 `MediaPipe Pose Landmarker` 수행
5. 사람별 상태를 메모리에 유지하며 실신 규칙 적용
6. 사람별 이동 이력을 누적하며 배회 규칙 적용
7. 이벤트 발생 시 클립 저장, 메타데이터 저장, 알림 생성
8. 관제 화면 또는 관리자 시스템에 이벤트 전달

### 3.2 모듈 책임
- `video_ingestion`
  - 영상 파일, RTSP 입력 처리
  - 프레임 샘플링
  - 타임스탬프 관리
- `person_tracking`
  - YOLO person detection
  - tracker 기반 `track_id` 유지
- `pose_analysis`
  - 사람별 pose landmark 추출
  - landmark 신뢰도 필터링
- `event_engine_fall`
  - 실신 상태 머신
  - 자세/속도/무동작 조건 계산
- `event_engine_wandering`
  - full-frame 기본 체류시간 계산
  - 필요 시 선택적 ROI 체류시간 계산
  - 반복 이동 패턴 계산
  - 배회 판정
- `clip_manager`
  - 이벤트 전후 클립 저장
  - 대표 프레임 저장
- `event_store`
  - 이벤트 메타데이터 저장
  - track 기반 상태 로그 저장
- `dashboard_api`
  - 이벤트 목록 제공
  - 정탐/오탐 피드백 수집

### 3.3 핵심 기술 선택
- 사람 검출 및 추적: `Ultralytics YOLO track`
- 권장 tracker: `ByteTrack`
- 자세 추출: `MediaPipe Pose Landmarker`
- 이벤트 판정: 규칙 기반 상태 머신

---

## 4. 이벤트 설계 요약

### 4.1 실신 탐지
목표:
- 갑작스러운 자세 붕괴와 이후 무동작 상태가 일정 시간 지속되는 상황을 감지

주요 입력:
- bbox 중심점 변화량
- bbox 가로/세로 비율 변화
- 어깨-엉덩이 또는 머리-엉덩이 축의 각도 변화
- landmark 평균 이동량

상태 흐름:
- `NORMAL`
- `FALL_SUSPECTED`
- `LYING_OR_COLLAPSED`
- `FALL_CONFIRMED`
- `RECOVERED`

1차 규칙 예시:
- 1초 이내 중심점 급하강
- 1초 이내 몸축 각도 급변
- bbox가 세로형에서 가로형으로 변화
- 이후 3초에서 5초 이상 landmark 이동량이 매우 작음

오탐 방지:
- 침대에 미리 누워 있던 인물 제외
- 앉기, 허리 숙이기 제외
- landmark 신뢰도 낮을 때 confidence 하향

### 4.2 배회 탐지
목표:
- 영상 전체를 기본 탐지 영역으로 사용해 목적 없는 반복 이동이 지속되는 패턴을 감지하고, 필요 시 선택적 ROI로 국소 구역을 보조적으로 제한

주요 입력:
- `track_id`
- 프레임별 bbox 하단 중심점(`bottom-center`)
- 전체 영상 영역 또는 선택적 ROI 기준 체류시간
- 이동 방향 변화 횟수
- 왕복 횟수
- 총 이동 거리와 순이동 거리 차이

배회와 체류 구분:
- `장시간 체류`: 오래 머무르지만 이동이 거의 없음
- `배회`: 같은 생활 동선 안에서 짧은 거리 이동과 방향 전환이 반복됨

1차 규칙 예시:
- 전체 화면 기준 체류시간 10분 이상
- 누적 왕복 횟수 4회 이상
- 방향 전환 횟수 임계치 이상
- 총 이동 거리는 크지만 순이동 거리는 작음

### 4.3 운영상 고려
- 처리 주기: 초기에는 5 FPS에서 10 FPS 수준으로 시작
- pose 적용 범위 최적화 필요
- 동일 이벤트 중복 발생 방지용 cooldown 또는 merge 로직 필요
- 배회는 `track_id` 품질이 매우 중요하므로 고정 복도 카메라부터 시작

### 4.4 이벤트 데이터 구조
tracking 로그:
- `timestamp_ms`
- `camera_id`
- `track_id`
- `bbox`
- `detection_confidence`

pose 로그:
- `timestamp_ms`
- `camera_id`
- `track_id`
- `pose_landmarks`
- `pose_confidence`

이벤트 로그:
- `roi_id` 또는 `full_frame`

이벤트 저장 예시:

```json
{
  "event_id": "evt_20260402_0001",
  "camera_id": "cam_01",
  "track_id": 17,
  "event_type": "wandering_suspected",
  "started_at": "2026-04-02T10:31:12+09:00",
  "ended_at": "2026-04-02T10:31:18+09:00",
  "confidence": 0.87,
  "roi_id": "full_frame",
  "clip_path": "events/cam_01/evt_20260402_0001.mp4",
  "snapshot_path": "events/cam_01/evt_20260402_0001.jpg",
  "description": "배회 의심: 전체 화면 기준 반복 이동이 지속됨",
  "status": "new"
}
```

---

## 5. 1차 구현 목표
초기 구현의 목표는 다음 end-to-end 흐름을 실제로 동작시키는 것이다.

1. CCTV 영상 또는 영상 파일 입력
2. 사람 검출 및 추적
3. 사람별 자세 추출
4. 실신 및 배회 규칙 적용
5. 이벤트 생성
6. 클립 및 스냅샷 저장
7. 이벤트 목록 확인

즉, 첫 단계에서는 높은 정확도보다도 `전체 파이프라인이 끝까지 연결되는 것`이 우선이다.

---

## 6. 구현 단계

### 6.1 프로젝트 골격 생성
목표:
- 코드와 설정, 산출물 경로를 고정한다.

작업:
- `backend/`
- `configs/`
- `data/`
- `artifacts/`
- `docs/`

산출물:
- 기본 디렉터리 구조
- 실행 엔트리포인트 파일
- 개발 환경 설정 파일

### 6.2 설정 파일 구조 정의
목표:
- 카메라, 임계치, 필요 시 ROI가 코드 밖에서 관리되게 한다.

작업:
- 카메라 설정 파일 포맷 정의
- 선택적 ROI 좌표 포맷 정의
- 실신 임계치 포맷 정의
- 배회 임계치 포맷 정의

예시:
- `configs/cameras/cam_01.yaml`
- `configs/rois/ward_corridor_a.yaml`
- `configs/thresholds/fall.yaml`
- `configs/thresholds/wandering.yaml`

기본 배회 탐지는 ROI 없이 전체 프레임을 사용하고, ROI 설정은 선택적 확장으로 둔다.

### 6.3 영상 입력 파이프라인 구현
목표:
- 영상 파일과 RTSP 입력을 동일한 처리 흐름으로 받을 수 있게 한다.

작업:
- 프레임 읽기
- FPS 샘플링
- 타임스탬프 생성
- 이벤트 전후 저장용 버퍼 구조 정의

산출물:
- 입력 모듈
- 샘플 영상 재생 테스트

### 6.4 YOLO track 연결
목표:
- 사람 검출과 `track_id` 부여를 안정적으로 수행한다.

작업:
- 사람 클래스만 필터링
- bbox, confidence, `track_id` 추출
- track별 히스토리 저장 구조 구현

산출물:
- 프레임별 detection/tracking 로그
- track 시각화 결과

### 6.5 MediaPipe Pose 연결
목표:
- 사람별 자세 추정 결과를 실시간으로 얻는다.

작업:
- bbox 기준 crop 생성
- 사람별 landmark 추출
- pose confidence 필터링
- landmark 좌표 정규화 방식 정의

산출물:
- pose 결과 로그
- pose overlay 샘플 영상

### 6.6 실신 규칙 엔진 구현
목표:
- 자세 변화 기반 실신 의심 이벤트를 생성한다.

작업:
- 중심점 급하강 계산
- 몸축 각도 변화 계산
- 무동작 시간 계산
- 상태 머신 구현

산출물:
- `fall_rule` 모듈
- 실신 이벤트 JSON

### 6.7 배회 규칙 엔진 구현
목표:
- 전체 영상 영역(full-frame) 기준 반복 이동 패턴을 기반으로 배회 의심 이벤트를 생성하고, 필요 시 선택적 ROI를 함께 지원한다.

작업:
- full-frame 기준 체류시간 계산
- 필요 시 ROI 진입/이탈 계산
- 방향 전환 횟수 계산
- 왕복 횟수 계산
- 배회 판정 로직 구현

산출물:
- `wandering_rule` 모듈
- 배회 이벤트 JSON

### 6.8 이벤트 저장 및 클립 생성
목표:
- 이벤트 결과를 사람이 확인 가능한 산출물로 남긴다.

작업:
- 이벤트 메타데이터 저장
- 이벤트 전후 클립 저장
- 대표 이미지 저장
- 이벤트 중복 방지 처리

산출물:
- `artifacts/events/`
- `artifacts/clips/`
- `artifacts/snapshots/`

### 6.9 최소 관제 화면 구현
목표:
- 담당자가 이벤트를 직접 확인할 수 있게 한다.

작업:
- 이벤트 목록 API
- 이벤트 상세 API
- 이벤트 목록 화면
- 클립 재생 화면
- 정탐/오탐 상태 변경 기능

산출물:
- 최소 대시보드
- 이벤트 확인 UI

---

## 7. 추천 구현 순서

### Sprint 1
- 프로젝트 골격 생성
- 설정 파일 포맷 정의
- 영상 입력 파이프라인 구현

### Sprint 2
- YOLO track 연결
- detection/track 시각화
- track 상태 메모리 구조 구현

### Sprint 3
- MediaPipe Pose 연결
- pose overlay 결과 확인
- pose 품질 기준 정의

### Sprint 4
- 실신 규칙 엔진 구현
- 실신 이벤트 저장
- 실신 샘플 영상 검증

### Sprint 5
- 선택적 ROI 설정 기능 구현
- 배회 규칙 엔진 구현
- 배회 샘플 영상 검증

### Sprint 6
- 클립 및 스냅샷 저장
- 이벤트 중복 제거
- 이벤트 JSON 저장

### Sprint 7
- 이벤트 목록 API
- 최소 대시보드 구현
- 정탐/오탐 피드백 기능

### Sprint 8
- 통합 테스트
- 임계치 조정
- 시연 시나리오 정리

---

## 8. 우선 구현 대상
처음부터 모든 기능을 동시에 만들지 말고, 아래 순서로 잠그는 것이 좋다.

1. `video -> YOLO track`
2. `video -> YOLO track -> MediaPipe Pose`
3. `video -> 실신 이벤트 생성`
4. `video -> 배회 이벤트 생성`
5. `video -> 이벤트 클립 저장`
6. `이벤트 목록 화면`

실신이 배회보다 더 짧은 시간축 이벤트이고 규칙 검증이 빠르므로, 구현 우선순위는 `실신 -> 배회`가 적절하다.

---

## 9. 초기 완료 기준
다음 조건을 만족하면 1차 MVP 파이프라인이 완성된 것으로 본다.

- 샘플 CCTV 영상에서 사람 검출 및 추적이 동작함
- 각 사람에 대해 pose landmark가 추출됨
- 실신 이벤트가 최소 한 가지 시나리오에서 탐지됨
- 배회 이벤트가 최소 한 가지 full-frame 시나리오에서 탐지됨
- 이벤트 발생 시 JSON, 클립, 스냅샷이 저장됨
- 이벤트 목록 UI에서 결과를 확인할 수 있음

---

## 10. 이후 확장 방향
- 여러 카메라 동시 처리
- 실시간 RTSP 안정화
- 이벤트 신뢰도 산출 고도화
- 선택적 ROI 편집 UI
- 모바일 알림 연동
- 규칙 기반 이후 후속 모델 고도화 검토

---

## 한 문장으로 정리
**이 구현 로드맵은 YOLO track과 MediaPipe Pose를 기반으로 실신과 배회를 규칙 엔진으로 판정하는 CCTV 서비스를, 사람 검출부터 이벤트 UI까지 단계적으로 구축하기 위한 실행 계획이다.**
