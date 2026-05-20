# 2026-05-18 작업기록 — velocity_smoother remapping 수정 + scp 경로 사고

## 1. 요약

3단계 검증 재개 전 velocity_smoother remapping 버그를 수정했다.
2026-05-16 작업기록 §6.3에서 발견했으나 미수정 상태로 남아 있던 것을 오늘 커밋으로 확정했다.
추가로 scp 경로를 잘못 지정해 수정이 미적용된 사고가 발생했고, 올바른 경로로 재전송해 해결했다.

---

## 2. 버그 1 — velocity_smoother remapping 오타

### 원인

nav2_velocity_smoother의 출력 토픽 내부명은 `cmd_vel_smoothed`인데,
2026-05-16 당시 `smoothed_cmd_vel → cmd_vel` 로 잘못 remapping해 미적용 상태였다.

**파이프라인 (수정 전 — 파이프라인 단절)**:
```
twist_mux → /cmd_vel_raw → velocity_smoother → (remapping 미적용) → /cmd_vel 미발행
→ 텔레옵/bt/cmd_vel 모두 모터 미전달
```

**파이프라인 (수정 후)**:
```
twist_mux → /cmd_vel_raw → velocity_smoother (cmd_vel_smoothed → cmd_vel) → /cmd_vel → zlac_driver
```

### 수정 내용

**파일**: `src/shared/vic_pinky/vicpinky_bringup/launch/bringup.launch.xml`

```xml
<!-- 수정 전 -->
<remap from="cmd_vel" to="cmd_vel_raw"/>

<!-- 수정 후 -->
<remap from="cmd_vel" to="cmd_vel_raw"/>
<remap from="cmd_vel_smoothed" to="cmd_vel"/>
```

**커밋**: `cbbb443` (vic_pinky `feature/dobi-npc-base`)

---

## 3. 버그 2 — scp 경로 오지정 사고 (2026-05-18)

### 원인

RPi는 `~/vicpinky_ws`에서 bringup을 실행하는데, 첫 번째 scp를 `~/moca/...` 경로로만 전송했다.
`run_vic_bringup.sh`가 `source ~/vicpinky_ws/install/setup.bash`를 사용하기 때문에
`~/moca`에 파일을 보내도 RPi bringup에 적용되지 않는다.

### RPi vicpinky_bringup 파일 경로 (정확한 경로)

```
~/vicpinky_ws/src/vic_pinky/vicpinky_bringup/launch/bringup.launch.xml   ← 소스 (이걸 수정)
~/vicpinky_ws/install/vicpinky_bringup/share/vicpinky_bringup/launch/bringup.launch.xml  ← install (이것도 덮어쓰기)
```

### 올바른 scp 명령어

```bash
# 소스
scp ~/moca/src/shared/vic_pinky/vicpinky_bringup/launch/bringup.launch.xml \
    vic@192.168.0.138:~/vicpinky_ws/src/vic_pinky/vicpinky_bringup/launch/bringup.launch.xml

# install (symlink-install 아닐 경우 별도 덮어쓰기 필요)
scp ~/moca/src/shared/vic_pinky/vicpinky_bringup/launch/bringup.launch.xml \
    vic@192.168.0.138:~/vicpinky_ws/install/vicpinky_bringup/share/vicpinky_bringup/launch/bringup.launch.xml
```

### 영향

- 수정이 적용 안 된 채로 bringup이 실행돼 텔레옵 불가 상태 지속
- 올바른 경로로 재전송 + bringup 재시작으로 해결

---

## 4. 핵심 교훈

| 항목 | 내용 |
|---|---|
| velocity_smoother 출력 토픽명 | `cmd_vel_smoothed` (smoothed_cmd_vel 아님) |
| RPi bringup 실행 워크스페이스 | `~/vicpinky_ws` (moca 아님) |
| scp 후 필수 작업 | **bringup 재시작** — 파일만 바꿔도 실행 중인 프로세스에 미적용 |

---

## 5. 3단계 잔여 검증 (다음 세션)

| 항목 | 상태 |
|---|---|
| velocity_smoother remapping 수정 | ✅ |
| 실물 사람 거리별 bh 값 측정 (1m/1.5m/2m) | 🔜 |
| close_threshold 최종 결정 + 정지 거리 검증 | 🔜 |
| 실물 2인 이상 멀티그룹 우선 접근 | 🔜 팀원 합류 후 |
