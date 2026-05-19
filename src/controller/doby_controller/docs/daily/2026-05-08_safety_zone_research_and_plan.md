# 2026-05-08 — 안전 영역 침입 일시정지/재개 기술 조사 + 적용 계획

## 변경 사항

코드 변경 없음 — 기술 조사 + 적용 계획 문서 단계.

신규/갱신 문서:
- **신규** `docs/cafe_npc_safety_zone.md` (836줄) — 학술 + 표준 + 현업 + ROS2 도구 통합 조사 + Phase A~F 적용 계획
- **갱신** `CLAUDE.md` §10 — "안전 영역 침입 일시정지/재개" 섹션 추가, 마지막 갱신 일자 2026-05-08
- **신규 메모리** `project_safety_zone_standards.md` — 표준 매핑 패턴 (Cat 2 + Monitored Standstill, 자동 재개 표준 허용)
- **신규 메모리** `project_cmd_vel_safety_pipeline.md` — ROS2 도구 토폴로지 (twist_mux + smoother + collision_monitor + zlac_driver 반드시 RPi 단일 호스트)
- **갱신 메모리** `MEMORY.md` — 인덱스 2개 항목 추가

작업 흐름: 4개 영역 (표준/규격, 학술 논문, 현업 사례, ROS2 도구) 을 4개 background subagent 로 병렬 조사 → 결과 종합 → 우리 시스템(Vic Pinky + BT.CPP + RPLiDAR + 카메라 2 + 노트북-RPi 분산) 매핑 → 적용 계획 (Phase A~F) 수립 → 문서 + 메모리 저장.

---

## 회고

### 잘된 것

1. **사용자 요구를 정확히 분리**: "abort vs pause" 의 차이를 첫 응답에서 명시 — 표준 차원에서도 IEC 60204-1 Cat 1 vs Cat 2 의 차이로 정합. 이게 전체 설계의 척추.
2. **4개 영역 병렬 조사**: 한 subagent 에 다 맡기지 않고 표준/학술/현업/도구 분리. 각 영역에서 다른 출처 (ISO docs, arXiv, 마케팅 자료, ROS2 docs) 를 활용해 깊이 확보. 총 100+ 출처 인용.
3. **현 시스템 자산 검증**: 학술/표준 결과가 우리 기존 자산 (1.0m 임계값, hysteresis 5프레임, abort_dwell_sec=2.0, 8 어휘 face_avatar, persona phrase pool) 의 정합성을 사후 검증. 새로 만들 게 줄어들고 기존 패턴 확장으로 충분.
4. **단계별 일정**: Phase A~E 가 D+1 ~ D+12 (실 작업 7~8일). 사용자 워크플로우 (한 단계씩 검증) 와 정합.

### 발견 (Discovery)

1. **EN ISO 13482 의 공공장소 갭** (Salem 2021 ACM TROHI) — 표준이 카페 같은 공공 출입 환경의 군중/돌발/proxemics 를 명시적으로 안 다룬다. 본 시스템의 BT funnel + emotional abort + 점주 override 가 이 갭을 보강하는 첫 실증 케이스 → 학술 논문 작성 시 강력한 contribution.
2. **현 1.0m 임계값의 표준적 합리성**: SSM 공식으로 Vic Pinky 0.3m/s + 100ms 응답 산출 시 ≈ 1.0~1.1m. 직관으로 정한 값이 표준 산식과 일치. 추가 정당화 가능.
3. **자동 재개는 표준 허용** — IEC 60204-1 Cat 2 + ISO/TS 15066 §5.5 모두 자동 재개 명시 허용. 단 e-stop 버튼은 ISO 13850 manual reset 의무 — 미래 점주 e-stop 추가 시 별도 회로.
4. **R15.08 비적용**: 산업/훈련된 인력 환경 한정 명시. 한국에서도 KS 채택 안 됨 (KS B ISO 13482 만 채택). 카페 호객 로봇은 ISO 13482 frame 으로 가야 정합.
5. **분산 DDS fail-open 위험**: cmd_vel 차단 4 노드 (twist_mux + smoother + monitor + zlac_driver) 가 노트북에 있으면 Wi-Fi 단절 시 zlac_driver 가 마지막 명령 그대로 유지 → 충돌 위험. **반드시 RPi 단일 호스트**. 우리 follow_controller 가 노트북에 있는 현 구조에서 cmd_vel watchdog 이 부재한 상태도 동시에 발견.
6. **collision_monitor + collision_detector 분리 운용 패턴**: monitor 는 물리 충돌 (cmd_vel 차단), detector 는 사회적 zone (1.2m Hall personal) 알람만 — 같은 패키지 안에 두 노드. 우리 BT abort_trigger 입력으로 detector_state 어댑터 추가하는 게 자연스러움.
7. **현업 사례에서 가장 정합도 높은 4개 모델**: Pudu BellaBot (pause-then-push), Diligent Moxi (intent signaling), Savioke Relay (호텔 좁은 복도 chirp+nod), MiR (2단 zone) — 우리 시스템은 이 4개의 결합 형태가 됨.

### 함정 / 메모

1. **Phase 후속 섹션 길이**: CLAUDE.md §10 이 길어지고 있음. 본 작업으로 30+ 줄 추가. 다음 회고 또는 phase 정리 시점에 §10 재구조화 고려 (해결됨/예정/장기 분리 더 명확히).
2. **메모리 2개 추가 vs 1개**: standards 와 pipeline 분리해서 저장. pipeline 이 도구 변경 (예: nav2 4.x 업그레이드) 시 갱신 빈도 더 높을 거라 분리. standards 는 잘 안 변함 (ISO 개정 추적).
3. **PL=d 인증 미획득** 명시 필요: ROS2 + BT.CPP 자체는 functional safety 인증 없음. 카페 환경은 best-effort safety 충분, 산업 인증 시점에서는 외부 검증 필요. 회고/논문 작성 시 명기 — `cafe_npc_safety_zone.md` §7.1 에 기록.

### 학술 척추 (cafe_npc_paper_master.md) 와 정합

본 작업은 6-Layer 청사진의 다음 layer 들과 직접 연결:
- **Layer 1 (Isla 2005 BT)** — ReactiveFallback alarm pattern 으로 SafetyCheck/EmotionMonitor/PauseGate 3계층 안전 분리
- **Layer 5 (Marzinotto 2014)** — BT 형식화의 priority safety 사상이 PauseGate 추가에 직접 정합
- **Layer 6 (Iovino 2022)** — "Safe AI" Open Challenge 4 종 중 하나가 본 작업의 직접 학술 근거. 향후 논문에서 본 시스템이 그 답안의 일부임을 명기 가능.

추가로:
- **ISO/TS 15066 SSM** + **ISO 13482** + **EC 60204-1** 표준이 6-Layer 와 별도의 "Layer 0 — 표준" 으로 추가될 수 있음. cafe_npc_paper_master.md 다음 갱신 시 검토.

---

## 다음 일정 (우선순위)

사용자 결정 대기 중인 결정 사항:
- [ ] Phase A (apt 설치 + twist_mux + cmd_vel rename) 시작 시점
- [ ] 신규 패키지 위치 (`dobi_npc_safety` 신설 vs 기존 `dobi_npc_emotion` 확장)
- [ ] Persona YAML safety section 의 페르소나별 zone 임계값 차등화 정책

병렬 가능한 다른 작업 (CLAUDE.md §10 의 미완료 항목):
- [ ] **SoT 문서 정정**: `docs/cafe_npc_camera_architecture.md` §3 (카메라 2 = abko, 2026-05-07 교체 반영) 일괄 갱신
- [ ] **follow_controller 재튜닝**: HCAM01N → abko 교체로 화각 변동, 라이브 재검증
- [ ] **운영자 모니터링 UI 확장**: `web/static/operator.html` + `teleop_server.py` (V/A 차트 + funnel 진행 + rapport 타임라인)

---

## 작업 통계

- 4개 background subagent 병렬 조사 (총 약 6분 누적)
- 산출물: 836줄 종합 보고서 + 회고 1편 + CLAUDE.md 갱신 + 메모리 2건
- 인용 출처: 100+ (ISO/IEC 표준 10+, 학술 논문 30+, 현업 제품 30+, ROS2 도구 30+)
- 코드 변경: 0 줄 (조사 + 계획 단계)

---

*작성: 2026-05-08*
*다음 회고 예정: Phase A 시작 시점 또는 다른 트랙 (SoT 정정, follow 재튜닝, operator UI) 진행 시*
