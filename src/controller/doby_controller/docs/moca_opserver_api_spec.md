# MOCA OpServer API 사양서

> **문서 ID**: `moca_opserver_api_spec.md`
> **버전**: v1.0 (2026-05-16)
> **작성자**: Stephen Kong (gjkong, PinkLAB)
> **상위 문서**: `moca_mode_and_opserver_plan.md` §4, §6.6
> **구현 대상**: `src/moca_opserver/` (신규 패키지)
> **워크스페이스**: `~/moca` (ROS2 Jazzy, Python 3.12, FastAPI, `ROS_DOMAIN_ID=22`)

---

## 0. 본 문서의 범위

본 문서는 `moca_opserver_node`의 외부 통신 인터페이스(REST + WebSocket)와 ROS 통신 인터페이스를 상세 명세한다.

### 0.1 본 문서가 다루는 것

1. REST API 엔드포인트 전체 (요청/응답 스키마, HTTP 상태 코드, 에러)
2. WebSocket 채널 메시지 스키마 (client→server, server→client)
3. ROS 토픽 구독/발행 매트릭스
4. 인증/권한 (선택 — M3)
5. 이벤트 큐와 우선순위 처리 로직
6. 모드 오케스트레이션 알고리즘 (선점 판단)

### 0.2 본 문서가 다루지 않는 것

- mode_manager의 FSM 동작 (`moca_5state_fsm_spec.md`)
- Web UI 화면 구성 (`moca_web_dashboard_spec.md`)
- patrol/guiding 내부 알고리즘 (각자 design 문서)

---

## 1. OpServer 아키텍처

### 1.1 단일 노드 / 멀티 책임

`moca_opserver_node`는 단일 ROS 노드 안에 다음 컴포넌트를 모듈로 호스팅한다:

```
moca_opserver_node (Python rclpy.Node)
│
├── REST Server (FastAPI + uvicorn, 별도 thread, port 8800)
│   └── rest_api.py
│
├── WebSocket Hub (FastAPI WebSocket, 같은 port 8800)
│   └── ws_hub.py
│
├── Event Queue (in-memory, idempotent)
│   └── event_queue.py
│
├── Mode Orchestrator (priority 판단 + SetMode 호출)
│   └── mode_orchestrator.py
│
├── Patrol Scheduler (5분 idle 타이머)
│   └── patrol_scheduler.py
│
├── Table Registry (TTL 캐시)
│   └── table_registry.py
│
├── Serving Queue (OpenARM → 서빙 큐)
│   └── serving_queue.py
│
└── Schemas (pydantic models)
    └── schemas.py
```

### 1.2 컴포넌트 책임 분리

| 모듈 | 입력 | 출력 | 책임 |
|---|---|---|---|
| `rest_api.py` | HTTP request | HTTP response | 라우팅, 검증 (pydantic), 응답 형식화 |
| `ws_hub.py` | WS frame | broadcast frame | 클라이언트 풀, 이벤트 fan-out |
| `event_queue.py` | dict | (큐 enqueue) | UUID idempotency, 시간 정렬 |
| `mode_orchestrator.py` | 이벤트 | SetMode service call | priority 판단, gating |
| `patrol_scheduler.py` | `/mode/state` + 시계 | 트리거 SetMode | 5분 idle dwell 감시 |
| `table_registry.py` | `TableReport` msg | dict 조회 | 점유 캐시 + TTL |
| `serving_queue.py` | pickup 이벤트 | (가공 후 큐) | 드링크 ↔ 테이블 매핑 |

### 1.3 데이터 흐름 다이어그램

```
                  ┌──────────────────────────────────────┐
                  │            FastAPI :8800             │
                  │  ┌────────────┐    ┌──────────────┐  │
                  │  │ REST       │    │ WebSocket    │  │
                  │  │ (POS,      │    │ (Browser     │  │
                  │  │  OpenARM)  │    │  Dashboard)  │  │
                  │  └─────┬──────┘    └──────┬───────┘  │
                  └────────┼──────────────────┼──────────┘
                           │                  │ ▲
                           ▼                  ▼ │
                  ┌───────────────────────────────────┐
                  │       event_queue (dedup)         │
                  └───────────────┬───────────────────┘
                                  ▼
                  ┌───────────────────────────────────┐
                  │      mode_orchestrator            │
                  │  (priority + battery + busy 확인) │
                  └───────────────┬───────────────────┘
                                  │ SetMode service
                                  ▼
                  ┌───────────────────────────────────┐
                  │       mode_manager (ROS)          │
                  └───────────────────────────────────┘

                  ┌───────────────────────────────────┐
                  │   ROS subscriptions               │
                  │   /mode/state                     │
                  │   /serving/state                  │   ws_hub
                  │   /patrol/state                   ├──▶ broadcast
                  │   /patrol/table_report            │   to browsers
                  │   /guiding/state                  │
                  │   /battery_state                  │
                  │   /opserver/event (self echo)     │
                  └───────────────────────────────────┘
```

---

## 2. REST API 명세

### 2.1 공통 규칙

- **Base URL**: `http://<opserver_host>:8800/api/v1`
- **Content-Type**: `application/json` (UTF-8)
- **인증**: M1 phase는 None (로컬망 한정). M3에서 API key (헤더 `X-API-Key`) 선택 적용.
- **타임아웃**: 클라이언트는 5초 권장.
- **재시도**: idempotent endpoint(`POST /pickup`, `POST /order`, `POST /guide`)는 `event_id` 헤더 또는 본문 필드로 dedup.

### 2.2 공통 응답 포맷

성공:
```json
{
  "status": "ok",
  "data": { ... },
  "ts": "2026-05-16T13:00:00.123Z"
}
```

에러:
```json
{
  "status": "error",
  "code": "INVALID_TABLE",
  "message": "table_id 'T99' is unknown",
  "ts": "2026-05-16T13:00:00.123Z"
}
```

### 2.3 에러 코드 사전

| code | HTTP | 설명 |
|---|---|---|
| `INVALID_PAYLOAD` | 400 | pydantic validation 실패 |
| `INVALID_TABLE` | 400 | 알 수 없는 table_id |
| `INVALID_MODE` | 400 | 알 수 없는 모드 |
| `DUPLICATE_EVENT` | 409 | 같은 event_id 재전송 |
| `ROBOT_OFFLINE` | 503 | `/mode/state` 3초 이상 미수신 |
| `BATTERY_LOW` | 503 | 배터리 부족, 활동 모드 불가 |
| `SAFETY_ALARM` | 503 | alarm dwell 내 |
| `BUSY` | 423 | mode_manager busy |
| `NO_EMPTY_TABLE` | 409 | guide 요청인데 빈 테이블 없음 |
| `INTERNAL_ERROR` | 500 | 그 외 |

### 2.4 엔드포인트 일람

| 메서드 | 경로 | 용도 | 인증 (M3) |
|---|---|---|---|
| GET | `/health` | 살아있는지 | 없음 |
| GET | `/status` | 종합 상태 (모드+배터리+큐+테이블) | 없음 |
| GET | `/tables` | 테이블 점유 현황 | 없음 |
| GET | `/tables/{id}` | 특정 테이블 상세 | 없음 |
| GET | `/queue/serving` | 서빙 큐 조회 | 없음 |
| GET | `/queue/guiding` | 동행안내 큐 조회 | 없음 |
| GET | `/events` | 최근 이벤트 로그 | 없음 |
| GET | `/config` | 현 설정 조회 | 없음 |
| GET | `/kpi/daily` | 일일 KPI | 없음 |
| GET | `/kpi/range` | 기간별 KPI | 없음 |
| POST | `/order` | POS 주문 접수 | API key |
| POST | `/pickup` | OpenARM 제조완료 | API key |
| POST | `/guide` | POS 동행안내 요청 | API key |
| POST | `/mode` | 수동 모드 전환 | 운영자 토큰 |
| POST | `/command` | 운영자 명령 (utter, stop 등) | 운영자 토큰 |
| POST | `/config` | 설정 갱신 (영업시간 등) | 운영자 토큰 |
| POST | `/emergency_stop` | 비상정지 | 운영자 토큰 |

### 2.5 각 엔드포인트 상세

#### GET /health

**용도**: 로드밸런서/모니터링용. ROS 연결 무관 항상 200.

```http
GET /api/v1/health

200 OK
{
  "status": "ok",
  "data": {"opserver_version": "0.1.0", "uptime_sec": 3600},
  "ts": "..."
}
```

---

#### GET /status

**용도**: 대시보드 초기 로드 시 1회 호출. 이후는 WS로 갱신.

```http
GET /api/v1/status

200 OK
{
  "status": "ok",
  "data": {
    "mode": {
      "current": "serving",
      "entered_at": "2026-05-16T12:34:00Z",
      "params": "{\"waypoint\":\"T03\",\"via_pickup\":true}",
      "battery_ok": true,
      "safety_ok": true,
      "last_reject_reason": ""
    },
    "battery": {
      "percentage": 0.78,
      "voltage": 12.4,
      "current": -2.1
    },
    "robot_online": true,
    "queue": {
      "serving": [
        {"drink_id":"D-0042","target_table":"T03","queued_at":"..."},
        {"drink_id":"D-0043","target_table":"T01","queued_at":"..."}
      ],
      "guiding": []
    },
    "tables": [
      {"id":"T01","occupancy":"empty","last_update":"...","confidence":0.92},
      {"id":"T02","occupancy":"occupied","person_count":2,...},
      ...
    ],
    "config": {
      "patrol_interval_minutes": 5,
      "patrol_enabled": true,
      "business_hours": "09:00-22:00",
      "battery_min": 0.20
    },
    "kpi_today": {
      "serving_count": 47,
      "patrol_count": 23,
      "guiding_count": 12,
      "engaging_count": 3
    }
  },
  "ts": "..."
}
```

---

#### GET /tables

**용도**: 테이블 모니터링 페이지.

```http
GET /api/v1/tables

200 OK
{
  "status":"ok",
  "data":{
    "tables":[
      {
        "id":"T01",
        "pose":{"x":-36.337,"y":0.526,"yaw":0.0,"frame_id":"map"},
        "occupancy":"empty",
        "person_count":0,
        "dishes_detected":false,
        "confidence":0.92,
        "last_update":"2026-05-16T12:30:01Z",
        "cumulative_serving_count":12,
        "cumulative_occupied_detected":34
      },
      ...
    ],
    "last_patrol_completed_at":"2026-05-16T12:30:01Z"
  },
  "ts":"..."
}
```

---

#### POST /order

**용도**: POS가 주문 접수 시 호출. 본 시점에 로봇 행동은 없음. 서빙 큐 사전 등록.

**호출 시점**: 결제 *완료 후 또는 주문 직후* (POS 정책). 본 endpoint는 단순 접수 + 큐 등록.

```http
POST /api/v1/order
Content-Type: application/json
X-API-Key: pos-xxxx

{
  "event_id": "ord-2026-05-16-0042",
  "order_id": "O-2026-05-16-0042",
  "customer_id": "C-anonymous-0017",
  "items": [
    {"sku":"AMERICANO","qty":1,"options":{"size":"R","ice":true}},
    {"sku":"LATTE","qty":1,"options":{"size":"L","ice":false}}
  ],
  "ordered_at": "2026-05-16T13:00:00Z"
}

200 OK
{
  "status":"ok",
  "data":{
    "order_id":"O-2026-05-16-0042",
    "expected_pickup_min":3,
    "queued_position":2
  },
  "ts":"..."
}

# 중복 event_id
409 Conflict
{"status":"error","code":"DUPLICATE_EVENT","message":"event_id already processed","ts":"..."}
```

**처리 흐름**:
1. event_queue에 idempotency 체크 (event_id)
2. serving_queue에 pending entry 등록 (drink_id 미배정 상태)
3. ws_hub broadcast `{"type":"order_placed",...}`

---

#### POST /pickup

**용도**: OpenARM이 음료 제조 완료 + 픽업 테이블 배치 완료 시점에 호출. **이 시점에 serving 모드 트리거**가 일어난다.

```http
POST /api/v1/pickup
Content-Type: application/json
X-API-Key: openarm-xxxx

{
  "event_id": "pkp-2026-05-16-0042-1",
  "drink_id": "D-2026-05-16-0042-1",
  "order_id": "O-2026-05-16-0042",
  "target_table": "T03",
  "via_pickup": true,
  "ready_at": "2026-05-16T13:03:00Z"
}

200 OK
{
  "status":"ok",
  "data":{
    "drink_id":"D-2026-05-16-0042-1",
    "serving_mode_requested": true,
    "queue_position": 1,
    "current_mode_before": "patrol",
    "preempted": true
  },
  "ts":"..."
}

# 거부: 배터리 부족
503 Service Unavailable
{"status":"error","code":"BATTERY_LOW","message":"battery 0.18 < min 0.20",...}

# 거부: 잘못된 테이블
400 Bad Request
{"status":"error","code":"INVALID_TABLE","message":"target_table 'T99' unknown",...}
```

**처리 흐름** (orchestrator의 핵심 분기):
1. event_id idempotency 체크
2. target_table valid 확인 (tables.yaml 매칭)
3. serving_queue.append({drink_id, target_table, via_pickup})
4. **gating logic**:
   ```
   if current_mode == 'serving': # 이미 서빙 중
       # 큐에만 추가, /serving/goto_table 토픽으로 통보
       publish_serving_goto_table(target_table)
       return {"queue_position": N, "preempted": False}

   elif current_mode in ('patrol', 'guiding', 'engaging'):
       if priority('serving') < priority(current_mode):  # 1 < 3,2,5 = True
           call_set_mode('serving', {"waypoint": target_table, "via_pickup": via_pickup})
           return {"preempted": True}

   elif current_mode == 'idle':
       call_set_mode('serving', {"waypoint": target_table, "via_pickup": via_pickup})
       return {"preempted": False}
   ```
5. ws_hub broadcast `{"type":"pickup_ready",...}`
6. SetMode 응답을 받으면 `/opserver/event` 토픽에 echo (디버깅)

---

#### POST /guide

**용도**: 카운터에서 결제 완료한 고객을 빈 테이블로 안내 요청.

```http
POST /api/v1/guide
Content-Type: application/json
X-API-Key: pos-xxxx

{
  "event_id": "gd-2026-05-16-0017",
  "customer_id": "C-2026-05-16-0017",
  "requested_at": "2026-05-16T13:00:00Z",
  "preferred_table": null,    // 또는 "T02" (점주 지정)
  "party_size": 2             // 2인 일행 (옵션)
}

200 OK
{
  "status":"ok",
  "data":{
    "customer_id":"C-2026-05-16-0017",
    "assigned_table":"T02",
    "eta_sec":18,
    "preempted":false
  },
  "ts":"..."
}

# 빈 테이블 없음
409 Conflict
{"status":"error","code":"NO_EMPTY_TABLE","message":"all tables occupied",...}
```

**처리 흐름**:
1. table_registry에서 occupancy="empty" 테이블 조회
2. preferred_table 지정 + 비어있으면 우선 할당, 아니면 가장 가까운 빈 테이블
3. gating:
   ```
   if current_mode == 'serving':  # priority 1 < 2, 거부 (Q에 추가 또는 reject)
       return 503/BUSY 또는 큐잉

   elif current_mode in ('patrol', 'engaging'):  # preempt
       call_set_mode('guiding', {"target_table":..., "customer_id":...})
       return {"preempted": True}

   elif current_mode == 'guiding':  # 이미 guiding 중
       guiding_queue.append(...)
       return {"queue_position": N}

   elif current_mode == 'idle':
       call_set_mode('guiding', ...)
       return {"preempted": False}
   ```

---

#### POST /mode

**용도**: 운영자 수동 모드 전환 (웹 UI 또는 외부 디버깅 도구).

```http
POST /api/v1/mode
Content-Type: application/json
X-Operator-Token: op-xxxx

{
  "mode": "engaging",
  "params": {"persona": "casual_browser"},
  "override_priority": false   // true면 priority 규칙 무시 (운영자 의도 우선)
}

200 OK
{
  "status":"ok",
  "data":{
    "current_mode_before":"idle",
    "current_mode_after":"engaging",
    "reason":"transition_started"
  },
  "ts":"..."
}

# mode_manager 거부
423 Locked
{"status":"error","code":"BUSY","message":"transition_in_progress",...}
```

**처리 흐름**:
1. mode와 params validate
2. `override_priority=true` (운영자 명시): priority 무시하고 즉시 SetMode 호출
3. `override_priority=false`: 일반 gating 적용
4. SetMode 결과 그대로 반환

---

#### POST /emergency_stop

**용도**: 비상정지. 즉시 idle + 5초 차단.

```http
POST /api/v1/emergency_stop
X-Operator-Token: op-xxxx

(빈 본문)

200 OK
{
  "status":"ok",
  "data":{"acknowledged":true,"blocked_until":"2026-05-16T13:00:05Z"},
  "ts":"..."
}
```

**처리 흐름**:
1. `/operator/command` 토픽에 `OperatorCommand{command_type:"stop_emergency"}` 발행
2. mode_manager는 이를 받아 즉시 강제 idle (priority 무시) + alarm dwell 시작
3. ws_hub broadcast 알람

---

#### POST /command

**용도**: 모드 외 미세 제어 (발화, 표정, 순회 건너뛰기 등).

```http
POST /api/v1/command
Content-Type: application/json
X-Operator-Token: op-xxxx

{
  "command_type": "utter",
  "payload": {
    "text": "안녕하세요!",
    "voice": "ko-KR-SunHiNeural",
    "face_expression": "happy"
  }
}

200 OK
```

지원 command_type:
- `utter`: 즉시 발화 (`UtterRequest` 발행, priority=10)
- `express`: 표정만 변경 (`/face_avatar/expression`)
- `skip_table`: patrol 중 특정 테이블 건너뛰기
- `resume`: emergency_stop 해제

---

#### POST /config

**용도**: 운영 설정 갱신.

```http
POST /api/v1/config
X-Operator-Token: op-xxxx

{
  "patrol_interval_minutes": 7,
  "patrol_enabled": true,
  "business_hours": "08:30-22:30",
  "battery_min": 0.25
}

200 OK
{"status":"ok","data":{"updated_keys":["patrol_interval_minutes","business_hours","battery_min"]},...}
```

**처리 흐름**:
1. opserver_config.yaml 디스크 저장
2. patrol_scheduler에 즉시 반영
3. battery_min은 mode_manager 파라미터 동적 갱신 (`SetParameters` 서비스 호출)

---

## 3. WebSocket 채널 명세

### 3.1 연결

**Endpoint**: `ws://<opserver_host>:8800/ws/dashboard`

**프로토콜**: 표준 WebSocket. 인증은 M3에서 connect 시 헤더 `X-Operator-Token`.

**연결 lifecycle**:
1. Client connect → server welcome 메시지 (현 status 스냅샷)
2. Client는 ping/pong로 keep-alive (30초 간격)
3. 끊김 시 client는 지수 백오프로 재연결 (1s → 2s → 4s ... 최대 30s)

### 3.2 메시지 공통 포맷

JSON only. 모든 메시지는 `type` 필드 보유.

```json
{"type": "<type_name>", "ts": "2026-05-16T13:00:00.123Z", ...payload}
```

### 3.3 Server → Client 메시지 (broadcast)

#### 3.3.1 welcome

연결 직후 1회.

```json
{"type":"welcome","ts":"...","data":{"snapshot": <GET /status 응답 전체>}}
```

#### 3.3.2 mode_state

`/mode/state` 토픽 수신 시마다 (1Hz).

```json
{
  "type":"mode_state","ts":"...",
  "data":{
    "current":"serving",
    "entered_at":"...",
    "params":"...",
    "battery_ok":true,
    "safety_ok":true,
    "last_reject_reason":""
  }
}
```

#### 3.3.3 battery

`/battery_state` 토픽 (1Hz로 다운샘플).

```json
{"type":"battery","ts":"...","data":{"percentage":0.78,"voltage":12.4}}
```

#### 3.3.4 robot_pose

`/odom` 토픽 (1Hz로 다운샘플, 평면도 마커용).

```json
{"type":"robot_pose","ts":"...","data":{"x":-36.5,"y":2.1,"yaw":1.2}}
```

#### 3.3.5 serving_progress

`/serving/state` 토픽 변화 시.

```json
{
  "type":"serving_progress","ts":"...",
  "data":{
    "state":"navigating","current_target":"T03",
    "queue":[{"drink_id":"D-0043","target":"T01"}],
    "eta_sec":12
  }
}
```

#### 3.3.6 patrol_progress

`/patrol/state` 토픽 변화 시.

```json
{
  "type":"patrol_progress","ts":"...",
  "data":{"state":"scanning","current_table":"T03","progress":0.6,"tables_visited":3}
}
```

#### 3.3.7 guiding_progress

`/guiding/state` 토픽 변화 시.

```json
{
  "type":"guiding_progress","ts":"...",
  "data":{
    "state":"moving","target":"T02","customer_id":"C-...",
    "distance_to_target":3.2,"customer_in_sight":true
  }
}
```

#### 3.3.8 table_update

`/patrol/table_report` 토픽 수신 시.

```json
{
  "type":"table_update","ts":"...",
  "data":{
    "table_id":"T02","occupancy":"occupied","person_count":2,
    "dishes_detected":false,"confidence":0.91
  }
}
```

#### 3.3.9 event_log

비즈니스 이벤트 발생 시 (POS, mode_change, alarm 등). 이벤트 피드에 표시.

```json
{
  "type":"event_log","ts":"...",
  "data":{
    "level":"info","source":"opserver",
    "msg":"pickup_ready: D-0042 → T03 (preempted patrol)",
    "category":"serving","event_id":"pkp-..."
  }
}
```

레벨: `info`, `warn`, `error`.

#### 3.3.10 alarm

긴급. 헤더 빨간 배너.

```json
{"type":"alarm","ts":"...","data":{"code":"battery_low","value":0.18,"severity":"high"}}
```

#### 3.3.11 config_updated

`/config` POST 후.

```json
{"type":"config_updated","ts":"...","data":{"updated_keys":[...]}}
```

### 3.4 Client → Server 메시지

웹 UI에서 발생. server는 받은 메시지를 검증 후 적절한 ROS service call 또는 토픽 발행.

#### 3.4.1 set_mode

```json
{"type":"set_mode","mode":"engaging","params":{"persona":"casual_browser"},"override_priority":false}
```

서버 처리: `POST /api/v1/mode`와 동일.

#### 3.4.2 emergency_stop

```json
{"type":"emergency_stop"}
```

서버 처리: `POST /api/v1/emergency_stop`와 동일.

#### 3.4.3 utter

```json
{"type":"utter","text":"안녕하세요","face_expression":"happy"}
```

서버 처리: `/utter/request` 토픽 발행 (priority=10).

#### 3.4.4 skip_table

```json
{"type":"skip_table","table_id":"T03"}
```

patrol 진행 중일 때만 유효. patrol_scheduler에 신호 전달 (TODO M2).

#### 3.4.5 set_config

```json
{"type":"set_config","patrol_interval_minutes":7,"business_hours":"08:30-22:30"}
```

서버 처리: `POST /api/v1/config`와 동일.

#### 3.4.6 ack_alarm

```json
{"type":"ack_alarm","alarm_code":"battery_low"}
```

UI에서 알람 확인 클릭. 서버는 향후 동일 알람 재전송 dedup 처리.

### 3.5 broadcast 전략

- 모든 WS 클라이언트에게 동일 메시지 fan-out (현 구현 단순)
- 클라이언트가 많아지면 (M3+) 페이지별 구독 (예: `subscribe: ["mode_state","battery"]`) 도입 검토

---

## 4. ROS 인터페이스 매트릭스

### 4.1 구독

| 토픽 | 메시지 타입 | 빈도 | 용도 |
|---|---|---|---|
| `/mode/state` | `dobi_npc_msgs/ModeState` | 1Hz | 현 모드 추적 → WS broadcast, orchestrator |
| `/serving/state` | `std_msgs/String` (JSON) | 1Hz | 서빙 큐/진행 → WS, `e_complete` 감지 |
| `/patrol/state` | `dobi_npc_msgs/PatrolState` | 1Hz | 순회 진행 → WS, `e_complete` |
| `/patrol/table_report` | `dobi_npc_msgs/TableReport` | event | table_registry 업데이트 → WS |
| `/guiding/state` | `dobi_npc_msgs/GuidingState` | 1Hz | 안내 진행 → WS, `e_complete` |
| `/battery_state` | `sensor_msgs/BatteryState` | 5Hz | 1Hz로 다운샘플 → WS |
| `/odom` | `nav_msgs/Odometry` | 20Hz | 1Hz로 다운샘플 → WS (로봇 위치 마커) |
| `/rapport/event` | `dobi_npc_msgs/RapportEvent` | event | abort_trigger 이벤트 로그 |

### 4.2 발행

| 토픽 | 메시지 타입 | 빈도 | 용도 |
|---|---|---|---|
| `/opserver/event` | `dobi_npc_msgs/OpEvent` | event | 외부 이벤트를 ROS 도메인에 echo (디버깅) |
| `/operator/command` | `dobi_npc_msgs/OperatorCommand` | event | 운영자 명령 (stop_emergency, utter 등) |
| `/serving/goto_table` | `std_msgs/String` | event | serving 큐에 항목 추가 |
| `/utter/request` | `dobi_npc_msgs/UtterRequest` | event | 운영자 발화 (priority=10) |

### 4.3 서비스 클라이언트

| 서비스 | 타입 | 용도 |
|---|---|---|
| `/mode/request` | `dobi_npc_msgs/srv/SetMode` | 핵심 - orchestrator가 호출 |
| `/mode_manager/set_parameters` | `rcl_interfaces/srv/SetParameters` | battery_min 등 동적 갱신 (M3) |

### 4.4 서비스 서버

| 서비스 | 타입 | 용도 |
|---|---|---|
| `/opserver/get_table_status` | `dobi_npc_msgs/srv/GetTableStatus` | (선택) 다른 ROS 노드가 조회 |
| `/opserver/set_patrol_schedule` | `dobi_npc_msgs/srv/SetPatrolSchedule` | (선택) CLI/스크립트에서 호출 |

---

## 5. 핵심 알고리즘

### 5.1 mode_orchestrator: 모드 전환 판단 (의사 코드)

```python
PRIORITY = {'serving':1, 'guiding':2, 'patrol':3, 'engaging':5, 'idle':99}

class ModeOrchestrator:
    def __init__(self, node):
        self.node = node
        self.cli_set_mode = node.create_client(SetMode, '/mode/request')

    def request_mode_change(self, target_mode: str, params: dict,
                             trigger_source: str,
                             override_priority: bool = False) -> dict:
        """
        target_mode 진입을 mode_manager에 요청.
        gating: priority 규칙 + 가드 사전 체크.
        """
        current = self.node.current_mode  # /mode/state 캐시
        battery = self.node.battery_pct
        safety_ok = self.node.safety_ok

        # 1. 사전 가드 (REST 응답을 빨리 거부 가능)
        if battery is not None and battery < self.node.battery_min and target_mode != 'idle':
            return {"ok": False, "code": "BATTERY_LOW", "value": battery}
        if not safety_ok and target_mode != 'idle':
            return {"ok": False, "code": "SAFETY_ALARM"}

        # 2. priority gating
        if not override_priority:
            if current != 'idle' and PRIORITY[target_mode] >= PRIORITY[current]:
                # 우선순위 같거나 낮음 → 거부 (또는 큐잉)
                return {"ok": False, "code": "BUSY",
                        "message": f"lower_priority_during_{current}"}

        # 3. SetMode 호출
        req = SetMode.Request()
        req.requested_mode = target_mode
        req.params = json.dumps(params) if params else ''

        future = self.cli_set_mode.call_async(req)
        # FastAPI 비동기 컨텍스트와 ROS executor 사이의 브리지
        result = await_ros_future(future, timeout=2.0)

        if result is None:
            return {"ok": False, "code": "INTERNAL_ERROR", "message":"setmode timeout"}

        return {
            "ok": result.success,
            "reason": result.reason,
            "current_mode_after": result.current_mode,
            "preempted": (current != 'idle' and target_mode != 'idle' and current != target_mode),
        }
```

### 5.2 patrol_scheduler: 5분 타이머 (의사 코드)

```python
class PatrolScheduler:
    def __init__(self, node):
        self.node = node
        self.last_idle_entered_at = None
        self.last_patrol_completed_at = None

    def on_mode_state(self, msg: ModeState):
        if msg.current_mode == 'idle':
            if self.last_idle_entered_at is None:
                # 새로 idle 진입
                self.last_idle_entered_at = self.node.get_clock().now()
        else:
            # 다른 모드 → idle dwell 리셋
            self.last_idle_entered_at = None

    def tick(self):  # 1Hz timer
        if self.last_idle_entered_at is None:
            return
        if not self.node.config.patrol_enabled:
            return
        if not in_business_hours(self.node.config.business_hours):
            return
        if self.node.battery_pct is not None and self.node.battery_pct < self.node.battery_min:
            return

        elapsed = (self.node.get_clock().now() - self.last_idle_entered_at).nanoseconds / 1e9
        if elapsed >= self.node.config.patrol_interval_minutes * 60:
            self.node.get_logger().info(f'patrol auto-trigger after {elapsed:.1f}s idle')
            self.node.orchestrator.request_mode_change(
                'patrol', {"sweep_mode": "all", "report_to_opserver": True},
                trigger_source='timer',
            )
            self.last_idle_entered_at = None  # 트리거 후 리셋
```

### 5.3 event_queue: idempotency (의사 코드)

```python
class EventQueue:
    def __init__(self, ttl_sec=3600):
        self.seen = {}  # event_id → ts
        self.ttl = ttl_sec

    def is_duplicate(self, event_id: str) -> bool:
        now = time.time()
        # GC
        self.seen = {k:v for k,v in self.seen.items() if now - v < self.ttl}
        if event_id in self.seen:
            return True
        self.seen[event_id] = now
        return False
```

### 5.4 e_complete 감지: 활동 모드 자동 idle 복귀

OpServer가 각 활동 모드의 state 토픽을 관찰하여 "임무 완료"를 감지하고 SetMode('idle') 호출.

```python
class CompletionWatcher:
    """각 활동 모드의 state 토픽에서 'idle'/'done'/'arrived' 같은 종료 시그널을
    n초 dwell 후 SetMode('idle')로 변환한다."""

    DWELL_SEC = {
        'serving': 3.0,   # /serving/state 'idle' 3초 dwell
        'patrol':  1.0,   # /patrol/state 'done' 1초 dwell
        'guiding': 5.0,   # /guiding/state 'arrived' 5초 dwell
        'engaging':2.0,   # /bt/result 받으면 2초 dwell
    }

    def on_serving_state(self, msg):
        if json.loads(msg.data).get('state') == 'idle':
            self._maybe_trigger_idle('serving')

    def on_patrol_state(self, msg):
        if msg.current_state == 'done':
            self._maybe_trigger_idle('patrol')

    def _maybe_trigger_idle(self, expected_mode):
        if self.node.current_mode != expected_mode:
            return
        # dwell 시작
        self._dwell_start[expected_mode] = now()
        # 다른 콜백/타이머에서 dwell 경과 시 SetMode('idle') 호출
```

---

## 6. 설정 파일

### 6.1 opserver_config.yaml

```yaml
# moca_opserver/config/opserver_config.yaml
opserver:
  host: "0.0.0.0"
  port: 8800
  log_level: "INFO"

policy:
  patrol_interval_minutes: 5
  patrol_enabled: true
  business_hours: "09:00-22:00"
  battery_min: 0.20
  alarm_dwell_sec: 5.0
  completion_dwell:
    serving: 3.0
    patrol: 1.0
    guiding: 5.0
    engaging: 2.0

ros:
  domain_id: 22
  setmode_timeout_sec: 2.0
  topic_subscriptions:
    mode_state: "/mode/state"
    serving_state: "/serving/state"
    patrol_state: "/patrol/state"
    patrol_table_report: "/patrol/table_report"
    guiding_state: "/guiding/state"
    battery: "/battery_state"
    odom: "/odom"
    rapport: "/rapport/event"

auth:  # M3에서 활성화
  enabled: false
  api_keys_file: "config/api_keys.yaml"
  operator_tokens_file: "config/operator_tokens.yaml"

kpi:
  storage: "sqlite"      # M3: redis 검토
  db_path: "/var/lib/moca/opserver_kpi.db"
  retention_days: 90
```

### 6.2 api_keys.yaml.example

```yaml
# moca_opserver/config/api_keys.yaml.example
api_keys:
  - key: "pos-xxxxxxxxxxxxxxx"
    name: "POS Counter"
    permissions: ["order", "guide"]
    created_at: "2026-05-01"

  - key: "openarm-xxxxxxxxxxxx"
    name: "OpenARM Drink Bot"
    permissions: ["pickup"]
    created_at: "2026-05-01"

operator_tokens:
  - token: "op-stephen-xxxxx"
    name: "Stephen Kong"
    permissions: ["all"]
```

---

## 7. 구현 체크리스트

### 7.1 M1 (필수)

- [ ] `moca_opserver` 패키지 scaffold (`package.xml`, `setup.py`, `resource/`)
- [ ] `opserver_node.py` 골격 (ROS 노드 + FastAPI thread 임베드)
- [ ] `GET /health`, `GET /status` 동작
- [ ] WS endpoint `/ws/dashboard` 동작, `welcome` + `mode_state` 전송
- [ ] `mode_orchestrator.py`: SetMode 클라이언트 + priority 사전 가드
- [ ] `POST /pickup` → SetMode 호출 동작
- [ ] `POST /mode` → SetMode 호출 동작
- [ ] `POST /emergency_stop` → `/operator/command` 발행 동작
- [ ] 단위 테스트: test_orchestrator (priority 매트릭스 5x5)
- [ ] launch 파일 `moca_opserver/launch/opserver.launch.py`

### 7.2 M2 (patrol/guiding 통합)

- [ ] `POST /guide` 처리 + table_registry 빈 테이블 조회
- [ ] `patrol_scheduler.py` 5분 idle 타이머
- [ ] `CompletionWatcher` 각 활동 모드 자동 idle 복귀
- [ ] `table_registry.py` TableReport 수집 + TTL 캐시

### 7.3 M3 (Web UI 연계)

- [ ] `GET /tables`, `GET /tables/{id}`, `GET /queue/*`
- [ ] `POST /config`, `GET /config` + yaml 영속화
- [ ] `POST /command` (utter, skip_table, resume)
- [ ] `GET /events` 이벤트 로그 페이지
- [ ] `GET /kpi/daily`, `GET /kpi/range`
- [ ] WS broadcast 전체 11종 메시지
- [ ] 인증 (API key + operator token)
- [ ] KPI sqlite 영속화

### 7.4 M4 (실기 통합)

- [ ] POS/OpenARM 실 API 연동 시나리오
- [ ] 1주 무중단 안정성
- [ ] 로그 로테이션, 모니터링 메트릭 export

---

## 8. 테스트 시나리오

### 8.1 단위 테스트 (test_orchestrator.py)

```python
# 5×5 priority 매트릭스 검증
@pytest.mark.parametrize("current,target,expected_ok", [
    ('idle', 'serving', True),
    ('idle', 'patrol', True),
    ('idle', 'guiding', True),
    ('idle', 'engaging', True),
    ('serving', 'patrol', False),     # lower priority during serving
    ('serving', 'guiding', False),
    ('serving', 'engaging', False),
    ('patrol', 'serving', True),      # preempt allowed
    ('patrol', 'guiding', True),      # preempt allowed
    ('patrol', 'engaging', False),    # lower priority
    ('guiding', 'serving', True),     # preempt
    ('guiding', 'patrol', False),
    ('guiding', 'engaging', False),
    ('engaging', 'serving', True),
    ('engaging', 'patrol', True),
    ('engaging', 'guiding', True),
])
def test_priority_gating(current, target, expected_ok):
    ...

# override_priority 동작
def test_override_priority_allows_any():
    ...

# 가드: 배터리/safety
def test_battery_low_rejects():
    ...
def test_safety_alarm_rejects():
    ...
```

### 8.2 통합 테스트

```bash
# T1: pickup → serving 트리거
ros2 launch dobi_npc_bringup dev_all.launch.py &
ros2 launch moca_opserver opserver.launch.py &
sleep 5
curl -X POST http://localhost:8800/api/v1/pickup \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: openarm-test' \
  -d '{"event_id":"t1-1","drink_id":"D-t1","target_table":"T03","via_pickup":true,"ready_at":"..."}'
sleep 2
ros2 topic echo /mode/state --once
# expected: current_mode='serving', params contains "T03"

# T2: 5분 idle → patrol 자동
sleep 305
ros2 topic echo /mode/state --once
# expected: current_mode='patrol'

# T3: WS 브로드캐스트 확인
wscat -c ws://localhost:8800/ws/dashboard
# expected first message: {"type":"welcome",...}
```

---

## 9. 미해결 이슈

| # | 이슈 | M1 결정 후보 |
|---|---|---|
| O1 | FastAPI와 rclpy executor 통합 방식 | (a) FastAPI를 별 thread (현 설계) (b) ros 노드를 asyncio task로 |
| O2 | SetMode async 호출의 timeout 처리 | (a) 2초 타임아웃 후 에러 (b) 응답 즉시 ok 반환, /mode/state로 후속 확인 |
| O3 | KPI 영속화 (M1엔 in-memory만) | (a) sqlite (b) redis (c) parquet 일일 dump |
| O4 | WS 다중 클라이언트 권한 차등 | (a) 동일 권한 (b) operator vs viewer |
| O5 | event_log 영속화 (현 in-memory) | M3에서 결정, 일단 N개 ring buffer |
| O6 | priority gating을 orchestrator vs mode_manager 어디서? | (a) orchestrator만 (현 설계) (b) mode_manager에서도 이중 체크 |

---

**End of Document**
