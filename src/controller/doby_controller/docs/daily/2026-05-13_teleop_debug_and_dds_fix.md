# 2026-05-13 텔레옵 디버깅 + DDS IP 고정 제거 + 모터 컨트롤러 초기화 강화

## 오늘 달성한 것

브라우저 텔레옵(W/A/S/D) 이 실제 로봇 이동으로 이어지는 전체 체인을 복구하고,
재부팅 후에도 안정적으로 기동되도록 두 군데를 패치했다.

---

## 1. DDS peer IP 하드코딩 제거 (run_teleop_ui.sh)

### 문제
`run_teleop_ui.sh` 가 RPi bringup 을 기동할 때 `ROS_STATIC_PEERS=$LAPTOP_IP` 를 환경변수로 주입했다.
노트북 DHCP IP 가 세션마다 바뀌면 bringup 이 이전 세션 IP 로 고정되어 다른 노트북에서는 DDS 발견이 실패했다.

### 원인 분석
FastDDS unicast 는 양방향으로 peer 를 알아야 한다.
- 노트북 → RPi: 노트북이 `ROS_STATIC_PEERS=192.168.0.138(RPi 고정 IP)` 설정 → 단방향 unicast 개시
- RPi → 노트북: RPi 에 `ROS_STATIC_PEERS=<LAPTOP_IP>` 없으면 RPi 가 먼저 접근 불가

단, 노트북이 먼저 discovery packet 을 RPi 에 보내면 RPi 는 그 패킷의 출처 IP 를 학습해서
`ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET` 만으로도 양방향 통신이 된다.
RPi 의 STATIC_PEERS 는 실제로 필요하지 않았다.

### 수정 내용 (run_teleop_ui.sh)
- RPi bringup 시동 명령에서 `export ROS_STATIC_PEERS=$LAPTOP_IP` 제거
- `unset ROS_STATIC_PEERS` 명시적으로 추가
- 기존 "IP 불일치 시 bringup 재시작" 로직도 단순화 (IP 체크 불필요)
- bringup 시작 전 포트 8765 자동 정리 추가 (이전 teleop_server 좀비 방지)

### 결과
같은 LAN(192.168.0.0/24)의 ROS_DOMAIN_ID=22 를 사용하는 모든 노트북이
RPi bringup 재시작 없이 접근 가능.

---

## 2. ZLAC 모터 컨트롤러 초기화 강화 (bringup.py)

### 문제
RPi 재부팅 후 bringup 이 반복 실패. 증상이 매번 달랐다:

| 시도 | 실패 단계 | 원인 |
|------|-----------|------|
| 1차 | step 6 (인코더 읽기) | 재시도 없이 1회 실패 → 즉시 종료 |
| 2차 | step 3 (motor enable) | 구형 bringup PID 2298 이 /dev/ttyUSB1 점유 중 |
| 3차 | step 2 (vel mode) | 동일 포트 점유 (더 이른 단계까지 전파) |

### 핵심 원인: 좀비 bringup 프로세스의 시리얼 포트 점유
`setsid nohup` 으로 기동된 bringup 의 자식 노드 (PID 2298) 가
`ros2 launch` 프로세스 종료 후에도 `/dev/ttyUSB1` (= `/dev/motor`) 를 점유하고 있었다.
새 bringup 이 같은 포트를 열어도 응답이 엉키거나 즉시 실패.

`fuser /dev/ttyUSB1` 으로 발견 → `kill -9 2298` 으로 해제.

### 수정 내용 (bringup.py — RPi + 로컬 백업 동기화)

**step 3 (motor enable)**: 재시도 5회 추가
```python
enable_ok = False
for en_attempt in range(5):
    if en_attempt > 0:
        self.driver.disable()
        time.sleep(0.3)
    if self.driver.enable():
        enable_ok = True
        break
    time.sleep(0.2)
```

**step 6 (encoder read)**: 300ms 대기 + 재시도 5회 추가
```python
time.sleep(0.3)
for enc_attempt in range(5):
    self.last_encoder_l, self.last_encoder_r = self.driver.get_position()
    if self.last_encoder_l is not None ...:
        enc_ok = True; break
    time.sleep(0.2)
```

### 재시작 스크립트 개선 (/tmp/restart_bringup3.sh)
- pkill 패턴 매칭이 SSH 세션 자체를 죽이는 문제 → SELF_PID/PARENT_PID 제외 로직
- 재시작 전 `colcon build --packages-select vicpinky_bringup` 자동 수행
- `ROS_STATIC_PEERS` 없이 기동

---

## 3. 텔레옵 WebSocket auto-reconnect (index.html)

### 문제
`wsTeleop` 이 서버 재시작 시 단순히 DISC 배지만 표시하고 재연결 안 함.
서버를 여러 번 재시작한 이번 세션에서 브라우저 새로고침을 잊으면 키 입력이 전달되지 않았다.

### 수정
`connectTeleop()` / `connectTelem()` 함수로 래핑, `onclose` 에서 2초 후 자동 재연결.

```js
function connectTeleop() {
    wsTeleop = new WebSocket(...);
    wsTeleop.onopen  = () => { setBadge(bConn, "b-ok", "OK"); clearTimeout(...); };
    wsTeleop.onclose = () => { setBadge(bConn, "b-err", "DISC"); setTimeout(connectTeleop, 2000); };
}
```

---

## 4. 로컬 vicpinky 백업 동기화

RPi `~/vicpinky_ws/src/vic_pinky/vicpinky_bringup/vicpinky_bringup/` 에서
노트북 `~/moca/src/shared/vic_pinky/vicpinky_bringup/vicpinky_bringup/` 로
`bringup.py` + `zlac_driver.py` 복사.

이 디렉토리는 `COLCON_IGNORE` 로 빌드에서 제외되지만
RPi 단독 수정분의 SoT 역할을 겸한다.

---

## 5. 최종 확인 항목

| 항목 | 결과 |
|------|------|
| RPi bringup 기동 | ✅ `Vic Pinky Bringup has been started successfully.` |
| /odom 발행 | ✅ 20Hz |
| DDS laptop→RPi /odom 수신 | ✅ 17~20Hz |
| RPi /joy/cmd_vel 수신 | ✅ 20Hz |
| 브라우저 텔레옵 W/A/S/D | ✅ 로봇 실제 이동 확인 |
| ROS_STATIC_PEERS(RPi) | ✅ 제거됨 (unset) |

---

## 6. 발견된 구조적 위험 및 후속 TODO

### 좀비 시리얼 포트 점유 (재발 가능)
- `setsid nohup` 자식이 launch 종료 후 생존하는 구조는 유지됨
- 재시작 스크립트(`restart_bringup3.sh`)가 현재는 수동 SCP 방식
- **후속**: `run_teleop_ui.sh` Step 3 에 `fuser /dev/motor` 체크 + 강제 해제 로직 추가 고려

### collision_monitor min_points
- 현재 RPi install yaml 에 `min_points: 99999` (실질 비활성)
- 텔레옵 동작 확인 후 적절한 값(예: 3~5)으로 복원 필요
- 로컬 `src/shared/vic_pinky/vicpinky_bringup/config/collision_monitor.yaml` 은 `min_points: 1` 원본 유지

### 다중 bringup 인스턴스
- 이번 세션 초반에 twist_mux 2개, collision_monitor 2개가 동시 실행된 사례 발생
- RPi 재부팅이 가장 확실한 정리 방법이지만, 운영 중 불가
- **후속**: bringup 시작 전 `fuser /dev/motor` 기반 포트 점유 확인을 run_teleop_ui.sh 에 통합

---

*작성: 2026-05-13*
*다음 갱신 예정: collision_monitor min_points 복원 + 운영 안정성 검증 후*
