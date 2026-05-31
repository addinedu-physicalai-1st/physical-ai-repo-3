# moca 시간 동기화 — 6대 chrony 설정

> 운영 노트북 + 노트북 2 + 5090 서버 1 + 로봇 2 = **6대** 동기화.
> 5090 서버를 LAN 마스터로, 나머지 5대를 client로 두는 단순 토폴로지.
> 인터넷 단절 (카페 환경) 시에도 LAN 내부 sync 유지.

---

## 토폴로지

```
[Internet NTP] (옵션)
       │
       ▼
┌─────────────────────────┐
│ 5090 서버 192.168.0.133 │  ← chrony master (allow + local stratum 8)
└────────┬────────────────┘
         │
   ┌─────┼─────┬─────┬─────┬─────┐
 노트북1  노트북2  노트북3  로봇1  로봇2
 (운영)              (192.168.0.138 Vic Pinky 서빙로봇 + 추가 1대)
```

| # | 호스트 | LAN IP | 역할 |
|---|---|---|---|
| 1 | 5090 서버 | `192.168.0.133` | **chrony master** |
| 2 | 운영 노트북 | (확정 후 기재) | client |
| 3 | 노트북 2 | (확정 후 기재) | client |
| 4 | 노트북 3 | (확정 후 기재) | client |
| 5 | 서빙 로봇 (Vic Pinky) | `192.168.0.138` | client |
| 6 | 추가 로봇 | (확정 후 기재) | client |

---

## 적용

### A. 5090 서버 (192.168.0.133, chrony master)

```bash
sudo apt install -y chrony
sudo cp server_5090.conf /etc/chrony/conf.d/moca.conf
sudo systemctl disable --now systemd-timesyncd   # 중복 NTP daemon 방지
sudo systemctl enable --now chrony
sudo systemctl restart chrony

# 검증 (60~90초 대기 후)
chronyc tracking            # Stratum / Last offset / Leap status: Normal
chronyc sources -v          # 인터넷 풀 reach 패턴 377
chronyc clients             # 5분 후 client 5대 누적
```

### B. 클라이언트 5대 (노트북 3 + 로봇 2)

```bash
sudo apt install -y chrony
sudo cp client.conf /etc/chrony/conf.d/moca.conf
sudo systemctl disable --now systemd-timesyncd   # ※ 충돌 회피 필수
sudo systemctl enable --now chrony
sudo systemctl restart chrony

# 검증
chronyc tracking            # Reference ID = 192.168.0.133 (또는 backup pool)
chronyc sources -v          # ^* 표시 = 현재 sync 중인 서버
timedatectl status          # System clock synchronized: yes
```

### C. 서빙 로봇 (192.168.0.138 Vic Pinky)

⚠ **CLAUDE.md §0-A 정책**: 팀이 실물 Vic Pinky 사용 중 신호 시 RPi 접근 금지.
사용자 명시 해제 시점에 위 "B. 클라이언트" 절차 동일 적용.

---

## 자주 발생 함정

1. **systemd-timesyncd + chrony 동시 실행 금지** — port 123 충돌.
   `sudo systemctl disable --now systemd-timesyncd` 필수.
2. **RTC 배터리 없는 RPi 5 모델** — 부팅 후 시간 jump 흔함. `makestep 1.0 3` 으로 자동 보정.
3. **인터넷 단절** — 5090 의 `local stratum 8` 설정으로 LAN-only stratum 8 master 역할 유지.
   5090 down 시 client 5대는 backup pool 로 대체 (있는 경우).
4. **방화벽** — 5090 측 UDP 123 (NTP) 인바운드 허용 필요.
   ```bash
   sudo ufw allow from 192.168.0.0/24 to any port 123 proto udp
   ```

---

## ROS-only 운영 상태

HTTP dashboard 는 제거되었다. NTP 상태는 운영 노트북에서 `chronyc tracking`
또는 `timedatectl show-timesync --all` 로 직접 확인한다.

**향후 (별 task)** — 6대 통합 sync 표시는 ROS topic/service reporter 로
분리한다. 각 호스트가 동기화 상태를 발행하고 `debug_monitor` 또는 별도
logging node 가 집계하는 형태를 권장한다.

---

## 검증 한 줄 명령

각 호스트에서:
```bash
timedatectl status | head -6 && chronyc tracking 2>/dev/null | head -8
```

5090 마스터에서 — 6대 토폴로지 한 번에:
```bash
chronyc clients
```
