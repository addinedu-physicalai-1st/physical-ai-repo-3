# MOCA 영구 DB 스키마 (M4)

> **문서 ID**: `moca_db_schema.md`
> **버전**: v0.1 초안 (2026-05-17)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **상위 문서**: `moca_opserver_api_spec.md` §9 미해결 O3-O5, `moca_web_dashboard_spec.md` M4 KPI
> **구현 대상**: `src/moca_opserver/` 확장 + 신규 `src/moca_reporter/` 후보
> **선행 회고**: `docs/daily/2026-05-16_m3_dashboard_completion_ntp_stopmoca.md` §3.2
>
> **⏸ 상태**: **5090 PostgreSQL 실 설치는 추후 연기** (2026-05-17 결정). 본 문서는 설계 SoT 로 유지, 인프라 작업은 별 트랙. 우선순위는 §12.1 참조.

---

## 0. 본 문서의 범위

본 문서는 moca 운영의 **영구 데이터** 저장 스키마 + 호스트 배치 + 보존/백업 정책을 명세한다.

### 0.1 본 문서가 다루는 것

1. DB 엔진 선택 (PostgreSQL on 5090) 의 근거
2. 3개 데이터베이스 분리 (`moca_orders` / `moca_telemetry` / `moca_kpi`)
3. 테이블 스키마 (DDL 초안)
4. ROS msg ↔ DB column 매핑 매트릭스
5. 인덱스 / 파티셔닝 전략
6. 보존 / 백업 / 반출 정책
7. PII / 보안 정책
8. `opserver_node` ↔ DB 통합 패턴 + reporter 노드 분리안
9. 마이그레이션 도구
10. 미해결 결정 사항

### 0.2 본 문서가 다루지 않는 것

- REST/WebSocket API 사양 (`moca_opserver_api_spec.md`)
- Web Dashboard 화면 구성 (`moca_web_dashboard_spec.md`)
- 시뮬 데이터 격리 정책 (§11.3 에서 보류 결정)
- 다매장 확장 (M5+ 별 문서)

---

## 1. DB 엔진 + 호스트

### 1.1 결정: PostgreSQL 16 on 5090

| 항목 | 결정 | 근거 |
|---|---|---|
| **엔진** | **PostgreSQL 16** | JSONB (RapportEvent.flags / OpEvent.payload 등 다수), 시계열 파티셔닝, partial index, PITR. 향후 TimescaleDB 확장 가능 |
| **호스트** | **5090 (192.168.0.133)** | NTP master 와 일관, 항상 가동, 강력 하드웨어, 노트북/RPi reboot 무관 |
| **포트** | `5432` (PG 기본) | LAN 내부만 허용 (`listen_addresses = '192.168.0.133, localhost'`), 외부 차단 |
| **인증** | `scram-sha-256` + per-host pg_hba | 5090 자신: trust, LAN(192.168.0.0/24): md5+password |
| **타임존** | `Asia/Seoul (KST)` | OS + PG `timezone` 양쪽. NTP 5090 master 가 KST 동기 |

### 1.2 대안 비교 (회고용)

| 엔진 | 채택 안 한 이유 |
|---|---|
| SQLite | 단일 writer 한계 (opserver + reporter + future telegram worker 동시 쓰기). 다호스트 query 불가 |
| MariaDB | JSONB 부재 (JSON 타입은 있으나 인덱싱 약함), partial index 없음, 시계열 파티셔닝 약함 |
| TimescaleDB | telemetry 만이라도 좋으나 orders 와 운영 분리 부담. M5+ 데이터 폭증 시 PG 확장으로 도입 |
| MongoDB | ACID 약함 — 구매 데이터에 부적합 |

### 1.3 운영 노드 배치

```
                      ┌──────────────────────────────┐
                      │ 5090 (192.168.0.133)         │
                      │                              │
                      │  PostgreSQL 16  ────┐        │
                      │  NTP master         │        │
                      │  (Grafana / Metabase│ M4+)   │
                      └─────────┬───────────┘        │
                                │ TCP 5432           │
              ┌─────────────────┼─────────────────┐  │
              │                 │                 │  │
        ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
        │ 노트북 #1 │     │ 노트북 #N │     │ RPi (Vic) │
        │ opserver  │     │ dashboard │     │ (telemetry│
        │ writer    │     │ read-only │     │   selected│
        │ (asyncpg) │     │           │     │   writes) │
        └───────────┘     └───────────┘     └───────────┘
```

- **쓰기 주체**: `opserver_node` (orders/telemetry/safety), `reporter_node` (kpi)
- **읽기 주체**: dashboard (analytics 페이지), telegram alert worker, 점주 모바일 (read-only)
- **RPi 직접 쓰기**: 보류 — 모든 쓰기는 노트북 opserver 경유 (네트워크 단절 대비 단순화). RPi 가 자체 보관해야 할 데이터 있으면 별 트랙

---

## 2. 데이터베이스 3개 분리

### 2.1 분리 이유

| DB | 목적 | ACID 엄격도 | 쓰기 패턴 | 보존 |
|---|---|---|---|---|
| **moca_orders** | 구매/결제 비즈니스 기록 | **엄격** (transaction, FK) | 사건 발생 시점만 (분당 수십 건) | **5년** (한국 세법) |
| **moca_telemetry** | 로봇 활동 로그 (모드 전이, rapport, utter, scan 등) | 보통 (event-level) | 고빈도 (초당 ~10건) | 1년 (이후 KPI 만 보존) |
| **moca_kpi** | 일/주/월 집계 (reporter batch 산출물) | 보통 | nightly batch | 무기한 |

분리하면:
- `moca_orders` 백업/복원이 빠름 (작은 DB)
- `moca_telemetry` 파티션 drop (월별) 이 다른 DB 영향 X
- 점주 폐업 시 `moca_orders` + `moca_kpi` 만 USB 반출, telemetry 는 선택

### 2.2 사용자 분리

```sql
CREATE USER moca_writer WITH PASSWORD '<env>';
CREATE USER moca_reader WITH PASSWORD '<env>';
CREATE USER moca_reporter WITH PASSWORD '<env>';

GRANT INSERT, UPDATE, SELECT ON ALL TABLES IN SCHEMA public TO moca_writer;  -- opserver
GRANT SELECT ON ALL TABLES IN SCHEMA public TO moca_reader;                  -- dashboard
GRANT SELECT, INSERT, UPDATE ON moca_kpi.* TO moca_reporter;                 -- nightly batch
```

---

## 3. `moca_orders` 스키마

비즈니스 기록 — 외부 POS 시스템과 게이트웨이.

### 3.1 `orders`

```sql
CREATE TABLE orders (
    order_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id         TEXT NOT NULL UNIQUE,             -- POS 측 idempotency key
    table_id         TEXT NOT NULL,                    -- T01..T05 (FK 미지정 — 매장 변경 자유)
    drink_id         TEXT NOT NULL,                    -- POS 측 메뉴 코드
    drink_name       TEXT,                             -- "아메리카노 (Hot)" 등 표시명
    customer_count   SMALLINT,                         -- nullable (POS 미제공 시)
    via_pickup       BOOLEAN NOT NULL DEFAULT TRUE,    -- /pickup 경유 여부
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending/ready/delivered/canceled
    ready_at         TIMESTAMPTZ,                      -- POS 가 보낸 준비 완료 시각
    pickup_started_at TIMESTAMPTZ,                     -- robot 이 picking 시작
    delivered_at     TIMESTAMPTZ,                      -- robot 이 테이블 도착 후 dispatcher dwell 종료
    canceled_at      TIMESTAMPTZ,
    canceled_reason  TEXT,                             -- "battery_low" / "safety_alarm" / "operator" 등
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata         JSONB                              -- POS 원본 payload 보존
);

CREATE INDEX idx_orders_created_at ON orders (created_at DESC);
CREATE INDEX idx_orders_table_id_status ON orders (table_id, status);
CREATE INDEX idx_orders_status_pending ON orders (created_at) WHERE status = 'pending';
```

### 3.2 `payments`

```sql
CREATE TABLE payments (
    payment_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id         UUID NOT NULL REFERENCES orders(order_id) ON DELETE RESTRICT,
    amount_krw       INTEGER NOT NULL,                 -- 원 단위 정수 (소수점 없음)
    method           TEXT NOT NULL,                    -- card/cash/kakaopay/zeropay 등
    receipt_no       TEXT,                             -- 현금영수증 번호
    tax_invoice_id   TEXT,                             -- 세금계산서 ID (사업자)
    paid_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    refunded_at      TIMESTAMPTZ,                      -- 환불 시점
    refund_reason    TEXT,
    metadata         JSONB
);

CREATE INDEX idx_payments_order_id ON payments (order_id);
CREATE INDEX idx_payments_paid_at ON payments (paid_at DESC);
```

### 3.3 보존

- **5년** (한국 세법 — 영수증/세금계산서 기록)
- WAL archiving + PITR (point-in-time recovery) 활성
- nightly `pg_dump --schema=public moca_orders` → 5090 외장 SSD + 매월 USB 반출

---

## 4. `moca_telemetry` 스키마

로봇 활동 로그 — 시계열, 파티셔닝.

### 4.1 `events` (일반 이벤트 — `OpEvent` 직렬화)

```sql
CREATE TABLE events (
    event_id     BIGSERIAL,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    source       TEXT NOT NULL,                       -- opserver/mode_manager/bt/face_avatar 등
    category     TEXT NOT NULL,                       -- system/mode/safety/order/guide/utter/info/warn/err
    level        TEXT NOT NULL,                       -- info/warn/err
    mode         TEXT,                                -- 발생 시점 current_mode
    message      TEXT,
    payload      JSONB,
    PRIMARY KEY (ts, event_id)                        -- 파티션 키 필수
) PARTITION BY RANGE (ts);

-- 월별 파티션 (pg_partman 또는 수동)
CREATE TABLE events_2026_05 PARTITION OF events
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

CREATE INDEX idx_events_ts_category ON events (ts DESC, category);
CREATE INDEX idx_events_payload_gin ON events USING GIN (payload);
```

### 4.2 `mode_transitions` — `ModeState` 변화 추적

```sql
CREATE TABLE mode_transitions (
    transition_id   BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_mode       TEXT NOT NULL,
    to_mode         TEXT NOT NULL,
    reason          TEXT,                             -- 'auto_idle_dwell' / 'pickup_preempt' / 'rapport_abort' / 'operator_force' 등
    triggered_by    TEXT,                             -- opserver/operator/completion_watcher/idle_patrol_timer
    duration_ms     INTEGER,                          -- 직전 모드 체류 시간
    params_json     JSONB,                            -- 진입 params (target_table 등)
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    error_code      TEXT
);

CREATE INDEX idx_mode_transitions_ts ON mode_transitions (ts DESC);
CREATE INDEX idx_mode_transitions_to_mode ON mode_transitions (to_mode, ts DESC);
```

### 4.3 `rapport_events` — Russell V/A + Salichs

```sql
CREATE TABLE rapport_events (
    rapport_id   BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type   TEXT NOT NULL,                       -- engagement_up/down/abort_trigger/neutral_continue
    weight       REAL NOT NULL,
    valence      REAL,                                -- -1.0 ~ +1.0
    arousal      REAL,                                -- -1.0 ~ +1.0
    confidence   REAL,
    source       TEXT,                                -- face/voice/fused
    flags        JSONB,                               -- ["mask_smile", "voice_only", ...]
    reason       TEXT,                                -- "anger_detected" 등
    mode         TEXT,                                -- 발생 시점 current_mode (engaging/idle 등)
    stage        TEXT                                 -- BT 5-stage (IDLE/APPROACH/ICEBREAK/...)
);

CREATE INDEX idx_rapport_ts ON rapport_events (ts DESC);
CREATE INDEX idx_rapport_abort ON rapport_events (ts) WHERE event_type = 'abort_trigger';
```

### 4.4 `minigame_results` — Castro-González 패러다임

```sql
CREATE TABLE minigame_results (
    result_id          BIGSERIAL PRIMARY KEY,
    ts                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    game_id            TEXT NOT NULL,                 -- rps_evolution / speed_counter / cafe_ninja
    rounds_played      SMALLINT NOT NULL,
    customer_wins      SMALLINT NOT NULL,
    robot_wins         SMALLINT NOT NULL,
    ties               SMALLINT NOT NULL,
    customer_win_rate  REAL NOT NULL,                 -- 목표 0.7 (학술 근거)
    duration_sec       REAL NOT NULL,
    completed          BOOLEAN NOT NULL,
    abort_reason       TEXT                           -- 미완 시 사유 (operator/timeout/rapport_abort)
);

CREATE INDEX idx_minigame_ts ON minigame_results (ts DESC);
CREATE INDEX idx_minigame_game_id ON minigame_results (game_id, ts DESC);
```

### 4.5 `patrol_runs` + `table_reports`

```sql
CREATE TABLE patrol_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    final_state     TEXT,                             -- done/aborted
    sweep_mode      TEXT,                             -- all/priority_only
    tables_total    SMALLINT,
    tables_scanned  SMALLINT,
    tables_skipped  SMALLINT,
    triggered_by    TEXT                              -- idle_patrol_timer/operator
);

CREATE TABLE table_reports (
    report_id        BIGSERIAL PRIMARY KEY,
    patrol_run_id    BIGINT REFERENCES patrol_runs(run_id) ON DELETE SET NULL,
    ts               TIMESTAMPTZ NOT NULL DEFAULT now(),
    table_id         TEXT NOT NULL,                   -- T01..T05
    occupancy        TEXT NOT NULL,                   -- empty/occupied/finished/unknown
    person_count     SMALLINT,
    dishes_detected  BOOLEAN,
    confidence       REAL,
    reason           TEXT,                            -- "no_model" / "stale_frame" / "nav_server_unavailable"
    snapshot_path    TEXT                             -- /data/moca/snapshots/2026/05/17/T03_142315.jpg (DB에 binary X)
);

CREATE INDEX idx_table_reports_ts ON table_reports (ts DESC);
CREATE INDEX idx_table_reports_table_occupancy ON table_reports (table_id, ts DESC);
```

### 4.6 `guiding_runs`

```sql
CREATE TABLE guiding_runs (
    run_id           BIGSERIAL PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    target_table     TEXT NOT NULL,
    customer_id      TEXT,                             -- 외부 시스템 식별자 (있으면)
    final_state      TEXT,                             -- arrived/aborted/done
    abort_reason     TEXT,                             -- "customer_lost"/"operator"/"safety"
    distance_traveled_m REAL,                          -- 추정값 (cmd_vel 적분 또는 odom diff)
    duration_sec     REAL
);

CREATE INDEX idx_guiding_ts ON guiding_runs (started_at DESC);
```

### 4.7 `safety_events` — 안전 영역 + emergency stop

```sql
CREATE TABLE safety_events (
    safety_id    BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind         TEXT NOT NULL,                       -- emergency_stop/zone_intrusion/abort/resume/battery_critical
    source       TEXT,                                -- operator/safety_check_node/collision_monitor/battery_node
    resolved_at  TIMESTAMPTZ,
    payload      JSONB                                -- zone info, battery_pct, scan_min_range 등
);

CREATE INDEX idx_safety_ts ON safety_events (ts DESC);
CREATE INDEX idx_safety_unresolved ON safety_events (ts) WHERE resolved_at IS NULL;
```

### 4.8 `utter_log` — 발화 기록

```sql
CREATE TABLE utter_log (
    utter_id        BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          TEXT NOT NULL,                    -- engaging_bt/serving/guiding/operator/safety
    persona         TEXT,                             -- casual_browser/friendly_child/professional_adult
    priority        SMALLINT,                         -- UtterRequest.priority (0=safety .. 255=lowest)
    text            TEXT NOT NULL,
    face_expression TEXT,                             -- basic/hello/happy/fun/interest/bored/sad/angry
    voice           TEXT,                             -- edge-tts voice id
    completed       BOOLEAN NOT NULL DEFAULT FALSE,
    preempted_by    TEXT
);

CREATE INDEX idx_utter_ts ON utter_log (ts DESC);
```

### 4.9 보존 + 파티셔닝

- `events` 만 월별 파티셔닝 (가장 빈도 높음). `pg_partman` 자동화 권장
- 다른 telemetry 테이블: 단일 테이블, 1년 후 archive 외장 SSD → DELETE
- KPI 집계 후 telemetry 파티션 drop 가능 (반복 불가능 데이터는 archive 보존)

---

## 5. `moca_kpi` 스키마

reporter 노드의 nightly batch 산출물.

### 5.1 `daily_summary`

```sql
CREATE TABLE daily_summary (
    date                    DATE PRIMARY KEY,
    -- 모드 카운트
    serving_count           INTEGER NOT NULL DEFAULT 0,
    patrol_count            INTEGER NOT NULL DEFAULT 0,
    guiding_count           INTEGER NOT NULL DEFAULT 0,
    engaging_count          INTEGER NOT NULL DEFAULT 0,
    serving_completed       INTEGER NOT NULL DEFAULT 0,
    serving_canceled        INTEGER NOT NULL DEFAULT 0,
    guiding_arrived         INTEGER NOT NULL DEFAULT 0,
    guiding_aborted         INTEGER NOT NULL DEFAULT 0,
    -- 영업
    orders_count            INTEGER NOT NULL DEFAULT 0,
    revenue_krw             BIGINT NOT NULL DEFAULT 0,
    avg_order_amount        INTEGER,
    -- 모객
    engaging_abort_count    INTEGER NOT NULL DEFAULT 0,
    avg_minigame_win_rate   REAL,
    avg_engagement_duration REAL,
    -- 안전
    emergency_stop_count    INTEGER NOT NULL DEFAULT 0,
    zone_intrusion_count    INTEGER NOT NULL DEFAULT 0,
    abort_trigger_count     INTEGER NOT NULL DEFAULT 0,
    -- 운영 시간
    uptime_sec              INTEGER,
    business_hours_active   BOOLEAN,
    -- 메타
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 5.2 `weekly_summary` + `monthly_summary`

`daily_summary` 의 column 군과 동일. PK 만 다름:
- `weekly_summary`: `(year SMALLINT, iso_week SMALLINT)` PRIMARY KEY
- `monthly_summary`: `(year SMALLINT, month SMALLINT)` PRIMARY KEY

reporter 가 nightly + Sunday weekly + 1일 monthly batch 로 생성.

### 5.3 `table_kpi` — 테이블별 점유

```sql
CREATE TABLE table_kpi (
    date            DATE NOT NULL,
    table_id        TEXT NOT NULL,
    empty_count     INTEGER NOT NULL DEFAULT 0,
    occupied_count  INTEGER NOT NULL DEFAULT 0,
    finished_count  INTEGER NOT NULL DEFAULT 0,
    avg_dwell_sec   REAL,
    orders_count    INTEGER NOT NULL DEFAULT 0,
    revenue_krw     BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (date, table_id)
);
```

---

## 6. ROS msg ↔ DB 매핑 매트릭스

| ROS msg / 이벤트 | 직접 매핑 테이블 | 부수 효과 |
|---|---|---|
| `ModeState` (1Hz) | `events` (필터: 변화 시점만) | `mode_transitions` 1행 |
| `PatrolState` (1Hz) | — (state 변화 시점만 sample) | `patrol_runs` (start/complete) |
| `TableReport` 발행 | `table_reports` 1행 | snapshot → filesystem path 만 저장 |
| `GuidingState` (1Hz) | — (state 변화 시점만) | `guiding_runs` (start/complete) |
| `EmotionState` (3-10Hz) | — (sample 또는 down-sample 1Hz, dashboard 만 raw) | rapport 발생 시 rapport_events 트리거 |
| `RapportEvent` | `rapport_events` | abort_trigger 시 `safety_events` 도 |
| `MinigameResult` | `minigame_results` | engaging 종료 시 `mode_transitions.reason` 갱신 |
| `OperatorCommand` | `events` (category='operator') | stop_emergency 시 `safety_events` 도 |
| `OpEvent` | `events` | — |
| `UtterRequest` 후 utter_done | `utter_log` | — |
| `/pickup` REST 요청 | `orders` INSERT | `events` category='order' |
| `/guide` REST 요청 | `guiding_runs` (target_table, customer_id 만 PRE) | `events` category='guide' |
| `/mode` REST 요청 (operator) | `mode_transitions.triggered_by='operator'` | `events` |
| `/emergency_stop` REST | `safety_events` kind='emergency_stop' | `mode_transitions.reason='emergency'` |
| `/battery_state` 1Hz | — (변화 임계 시 sample) | percentage < battery_min 진입 시 `safety_events` |
| `/odom` 20Hz | **저장 안 함** (dashboard 만 실시간) | run 종료 시 distance_traveled_m 계산용 적분만 |

### 6.1 down-sampling 규칙

- 1Hz 이상 발행: 변화 임계 통과 시점만 (delta-based)
- `events.payload` JSONB 에 raw 일부 보존 (디버깅)
- 미가공 raw 가 필요한 경우 — `ros2 bag record` 별도 트랙

---

## 7. 인덱스 + 파티셔닝

### 7.1 인덱스 전략

| 패턴 | 적용 |
|---|---|
| 시계열 query | 모든 테이블에 `ts DESC` index |
| 카테고리 필터 | `events (ts DESC, category)` 복합 |
| 상태 필터 | partial index — 예: `WHERE status='pending'` |
| JSONB 조회 | `GIN` index — 예: `events.payload` |
| FK | 자동 X — 수동 INDEX 필수 (PG 기본 미생성) |

### 7.2 파티셔닝

`events` 만 — 월별 RANGE 파티션:
- `pg_partman` 자동 생성 + 13개월 보존 후 drop
- 다른 telemetry 테이블: 단일 테이블 + 연 1회 archive

### 7.3 VACUUM + ANALYZE

- 기본 autovacuum 활성
- 월말 + 파티션 drop 후 수동 `VACUUM ANALYZE` cron

---

## 8. 보존 / 백업 / 반출

### 8.1 보존 정책

| DB | 보존 | 이유 |
|---|---|---|
| `moca_orders` | **5년** | 한국 세법 (영수증/세금계산서) |
| `moca_telemetry` | 1년 (events 13개월) | 운영 디버깅 / 학술 데이터 |
| `moca_kpi` | 무기한 | 작음 (월별 ~10KB) |
| snapshot 이미지 | 30일 (M5 결정) | PII (얼굴 포함 가능), 용량 |

### 8.2 백업

```bash
# nightly (cron 03:00 KST on 5090)
pg_dump -d moca_orders   --format=custom --file=/data/backup/moca_orders_$(date +%F).dump
pg_dump -d moca_kpi      --format=custom --file=/data/backup/moca_kpi_$(date +%F).dump

# WAL archiving (PITR)
archive_command = 'cp %p /data/wal_archive/%f'

# 외장 SSD rsync (월 1회)
rsync -av /data/backup/ /mnt/external_ssd/moca_backup/

# 점주 USB 반출 (분기 1회 또는 폐업 시)
# moca_orders + moca_kpi + 30일 snapshot ZIP
```

### 8.3 점주 데이터 소유권

- moca 가 점주에게 매장 사용권 제공 시 → **점주가 데이터 소유**
- 폐업/계약 종료 시: 위 USB 반출 + 5090 측 데이터 삭제 + DELETE 확인서

---

## 9. PII + 보안

### 9.1 PII 식별

| 항목 | 위치 | 정책 |
|---|---|---|
| 얼굴 이미지 | `table_reports.snapshot_path` 가 가리키는 filesystem | 30일 보존 (M5 결정). 얼굴 블러 옵션 검토 |
| 사람 수 (`person_count`) | `table_reports` | 집계 정보 — PII 아님 |
| V/A 감정 raw | `rapport_events` | 익명 (customer_id 없음). 학술 데이터 |
| 결제 정보 | `payments.receipt_no`, `tax_invoice_id` | 한국 개인정보보호법 적용 — 5년 후 즉시 폐기 |
| 음성 transcript (M5+) | — | 본 문서 범위 외. 도입 시 별 정책 |

### 9.2 access control

- DB 사용자 분리 (§2.2)
- web dashboard 인증 (M4 — `moca_opserver_api_spec.md` §9 O4)
- 모바일 read-only 토큰 (사장님 전용)

### 9.3 sim/real 분리

미해결 — §11.3 결정 보류.

---

## 10. opserver_node ↔ DB 통합 패턴

### 10.1 라이브러리

- `psycopg[binary]` 3.x (async) 또는 `asyncpg` — FastAPI/uvicorn asyncio 와 정합
- SQLAlchemy 2.x **선택** — ORM 대신 Core 사용 (마이그레이션 + 타입 안전)

### 10.2 connection pool

```python
# opserver_node 초기화 시
pool = await asyncpg.create_pool(
    host='192.168.0.133', port=5432,
    user='moca_writer', password=os.environ['MOCA_DB_PASSWORD'],
    database='moca_orders',  # 별도 pool x3 (orders/telemetry/kpi)
    min_size=2, max_size=10,
    command_timeout=5.0,
)
```

### 10.3 write fallback (DB unreachable)

- ROS 콜백 → 로컬 buffer (deque maxlen=5000) → 별 thread 가 DB flush
- DB 복귀 시 buffer drain
- buffer overflow 시 `events.level='warn'` 자체 기록
- 노트북 ↔ 5090 LAN 끊김 대비 (Wi-Fi 약함 시)

### 10.4 reporter_node 분리 (M4 후반)

```
src/moca_reporter/
├── reporter_node.py        # daily/weekly/monthly batch
├── aggregator.py           # telemetry → kpi 집계 로직
└── launch/reporter.launch.py
```

- 실행 주기: 5090 cron (호스트는 노트북 1대 또는 5090 직접)
- 03:30 KST nightly (백업 후)
- /api/v1/kpi/* endpoint 의 backing 데이터 제공

### 10.5 dashboard read 경로

```
analytics.html
  → GET /api/v1/kpi/daily?from=2026-05-01&to=2026-05-17
  → rest_api.py: moca_kpi pool select
  → Chart.js render
```

snapshot 직접 표시 — `/static/snapshots/...` mount (별 작업 필요).

---

## 11. 마이그레이션 + 미해결

### 11.1 마이그레이션 도구

- **Alembic** (SQLAlchemy 기반) 채택 권장
- `src/moca_opserver/migrations/`
  - `versions/0001_initial.py` — orders/payments/events/...
  - `versions/0002_*.py` — 이후 변경
- `alembic upgrade head` 가 opserver_node 기동 시 자동 실행 (또는 별 step)

대안: raw SQL files + 자체 version 테이블 (간단하지만 rollback 약함)

### 11.2 초기 데이터

- `tables.yaml` 의 T01-T05 좌표를 별도 `tables_meta` 테이블로 동기? 또는 yaml 만 SoT 유지?
- → SoT 는 yaml. DB 의 table_id 는 단순 TEXT FK 없이 사용 (매장 변경 자유)

### 11.3 미해결 결정 사항

| # | 이슈 | 보류 사유 |
|---|---|---|
| D1 | sim (DOMAIN=99) 데이터를 같은 DB 에 저장? | 옵션 A 별 schema(`moca_telemetry_sim`) / B `events.payload.domain` 필드 / C 저장 안 함. M4 초기 결정 |
| D2 | snapshot 이미지 보존 기간 | 30일 가정 (§9.1), 점주 정책에 따라 조정 |
| D3 | TimescaleDB 도입 시점 | 1년 후 telemetry 30M rows + 응답 느려지면. M5+ |
| D4 | read replica 필요? | 단일 매장 + 점주 모바일 1-2명 → 불필요. 다매장 시 재검토 |
| D5 | encryption at rest | LAN 내부 + 5090 자체 보관 가정 — pg_crypto / LUKS 필요 시 추후 |
| D6 | event 카테고리 분류 ENUM 정의 | UI 의 6 카테고리 (`moca_web_dashboard_spec.md`) 와 정합 — `system/mode/safety/order/guide/utter` 외 확장 시 명문화 필요 |
| D7 | snapshot binary 를 DB 에 둘 가능성 | 일관성/단순화 위해 추후 검토 (현 filesystem 권장) |
| D8 | reporter 실행 위치 | 5090 cron vs 노트북 cron vs ROS 노드 — M4 진입 시 결정 |
| D9 | downsample 기준 (`/odom`, `EmotionState`) | 1Hz 통일 권장하나 학술 데이터 raw 필요성 검토 |
| D10 | 다매장 확장 시 schema 변경 | `cafe_id` column 도입 vs DB per cafe. M5+ 별 문서 |

---

## 12. 다음 단계

### 12.1 설계 단계 (본 문서 범위, PG 설치 무관)

- [ ] D1 (sim 데이터 정책) 결정 → 본 문서 갱신
- [ ] D6 (event 카테고리 ENUM) 정의 — `moca_web_dashboard_spec.md` 와 정합
- [ ] D8 (reporter 실행 위치) 결정
- [ ] DDL 초안 SQL 파일화 (`docs/sql/0001_initial.sql`) — 5090 미설치 상태에서도 schema review 가능

### 12.2 인프라 설치 (별 트랙, 추후)

- [ ] 5090 에 PostgreSQL 16 설치 + `pg_partman` 확장 + 사용자 3종 생성
- [ ] Alembic 초기 마이그레이션 (`0001_initial.py`) 작성 + 5090 적용
- [ ] `opserver_node` connection pool 3종 + 최소 4 테이블 write (`orders` / `mode_transitions` / `events` / `rapport_events`)
- [ ] write fallback buffer (§10.3)
- [ ] `analytics.html` 에 `/api/v1/kpi/daily` 연결 (in-session 카운트 → DB read)

### 12.3 M4 중반 (PG 가동 후)

- [ ] reporter_node 작성 + nightly batch 검증
- [ ] 1주 라이브 데이터 누적 + 백업/복원 dry-run
- [ ] PII 30일 cleanup cron
- [ ] D2~D6 결정 + 본 문서 갱신

### 12.4 M5+

- [ ] TimescaleDB 도입 검토
- [ ] read replica
- [ ] 다매장 확장 schema
- [ ] 인증/권한 차등 (operator vs viewer)

---

## 13. 관련 메모리 / 문서

- `[[project_ntp_topology_5090_master]]` — 5090 호스트 정합
- `[[feedback_dont_touch_working_code]]` — 본 도입 시 기존 opserver 동작 보존 (옵션 flag 로 활성)
- `[[feedback_relative_path_convention]]` — connection 정보는 환경변수 (`MOCA_DB_HOST`, `MOCA_DB_PASSWORD`)
- `[[project_m3_dashboard_complete]]` — analytics 페이지 backing 데이터 공급
- `[[feedback_no_rpi_when_team_working]]` — RPi 측 DB 쓰기 보류 (§1.3)
- 회고 `2026-05-16_m3_dashboard_completion_ntp_stopmoca.md` §3.2 — 본 문서 모태

---

*작성: 2026-05-17. 다음 갱신: D1 (sim 분리) 결정 + 5090 PG 설치 후*
