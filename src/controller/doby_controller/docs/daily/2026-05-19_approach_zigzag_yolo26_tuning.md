# 2026-05-19 — approach 모드 지그재그 수정 + YOLO26 GPU 전환

> 작성: 2026-05-19 (doby)
> 세션 시간: 오후 (approach 지그재그 진단 + 코드 수정 + YOLO26 벤치마크)
> 브랜치: feature/dobby-follower

---

## 0. 본 세션 목적

run_follower.sh 전체 검증 전 approach 모드 지그재그 문제 원인 파악 및 수정.

---

## 1. 발견한 문제

### 1.1 approach 모드 지그재그 진동

로봇이 그룹을 향해 접근할 때 좌우로 흔들리며 오는 증상.

**원인 분석:**
- 원인 1: `/customer_pose` 가 4-5Hz 불규칙 발행 (YOLO + BoT-SORT + MediaPipe 처리 부하 누적)
- 원인 2: 불규칙한 업데이트 간격에서 D항(derivative) 스파이크 발생
- 원인 3: 거리가 가까워질수록 픽셀 공간에서 과하게 반응 (거리 비례 Kp 없음)
- 원인 4: MediaPipe Pose가 시각화 목적으로 불필요하게 실행 중 (CPU 낭비)

---

## 2. 코드 수정 내용

### 2.1 person_tracking_node.py

- **MediaPipe 완전 제거**: 시각화 전용이었음. 1인 추종은 person_detector_node가 별도 담당
- `frame_skip` 파라미터 추가 (GPU 사용 시 기본값 1 = 전 프레임 처리, CPU 시 3 권장)
- `yolo_device` 파라미터 추가 (`'cpu'` 또는 `'cuda:0'`)
- YOLO 추론 시 `device` 파라미터 전달

제거된 항목: colorsys, color palette, `_draw_skeleton`, `_draw_boxes`, `publish_visualization`, `pose_model_path`

### 2.2 approach_controller_node.py

- **cx/cy에 EMA 필터 추가** (`pose_ema_alpha=0.4`): YOLO 탐지 노이즈로 인한 좌우 튀는 값 완화
- **bh 기반 거리 비례 Kp 추가**:
  - `angular_gain` (kp_far): 0.8 (멀 때)
  - `kp_near`: 0.3 (가까울 때)
  - `bh_near`: 0.5 (bbox 높이 비율 기준)
  - 선형 보간: `t = min(1.0, bh / bh_near)`, `kp = kp_far + (kp_near - kp_far) * t`
- `dead_zone`: 0.05 → 0.10 (무감대 확대)

### 2.3 dev_common.launch.py

- `publish_visualization` 파라미터 제거
- `yolo_model_path`: `'yolo26n.pt'` 추가
- `yolo_device`: `'cuda:0'` 추가

---

## 3. YOLO26 벤치마크 결과

| 모델 | 환경 | 추론 시간 | FPS |
|---|---|---|---|
| YOLOv8n | CPU | 22.2ms | 45fps |
| YOLO26n | CPU | ~7.5ms | — |
| YOLO26n | GPU (RTX 4060) | 6.9ms | 146fps |

GPU 사용 시 YOLOv8n CPU 대비 **69% 향상**. yolo26n.pt 다운로드 완료 (작업 폴더).

**기술 결정**: YOLO26n + GPU 채택. YOLOv8에서 전환.

---

## 4. 다음 세션 진입점 (2026-05-20)

1. run_follower.sh 재시작 후 수정된 코드로 테스트
2. approach 지그재그 해결됐는지 라이브 확인
3. 파라미터 fine-tuning (필요시)

---

*다음 갱신: 2026-05-20 라이브 테스트 후*
