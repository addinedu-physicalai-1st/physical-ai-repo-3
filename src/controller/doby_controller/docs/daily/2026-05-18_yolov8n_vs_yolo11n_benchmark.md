# 2026-05-18 작업기록 — YOLOv8n vs YOLO11n 벤치마크

## 1. 배경

학술 발표/질의응답 대비 — "왜 최신 YOLO11이 아닌 v8을 썼나?" 질문에 대한 근거 확보 목적.

---

## 2. 환경

- **venv**: `~/venv/yolo_venv` (ultralytics 8.4.7)
- **GPU**: NVIDIA GeForce RTX 4060 Laptop GPU (CUDA)
- **입력**: 640×480 더미 이미지, 50프레임 평균

---

## 3. 결과

| 모델 | ms/frame | FPS |
|---|---|---|
| YOLOv8n | 4.3ms | 230 FPS |
| YOLO11n | 5.9ms | 169 FPS |

**YOLOv8n이 약 1.6ms (37%) 더 빠름.**

---

## 4. 결론

YOLO11n이 정확도는 소폭 높지만 속도는 v8n이 우세.
실시간 사람 감지 용도에서 속도가 더 중요하므로 **YOLOv8n 유지**.

질의응답 답변: *"벤치마크 결과 v8n이 오히려 더 빠르고 정확도 차이도 미미해서 v8n을 선택했습니다."*
