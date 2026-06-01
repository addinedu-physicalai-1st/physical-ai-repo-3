#!/usr/bin/env bash
# capture_waypoint.sh — teleop 으로 목적지 정차 후 현재 /amcl_pose(map 좌표) 를
#   config/waypoints_mapv6_capture.yaml 의 waypoints: 블록에 한 줄로 저장한다.
#
# 사용법:
#   scripts/capture_waypoint.sh <ID>             # 캡처 + yaml 저장 (.bak 백업)
#   scripts/capture_waypoint.sh <ID> --dry-run   # 저장 없이 yaml 한 줄만 출력(미리보기)
#   <ID> = 웨이포인트 이름 (예: W13, T03). 같은 ID 가 이미 있으면 그 줄을 갱신.
#
# 도메인: 호출 셸의 ROS_DOMAIN_ID 를 그대로 사용 (sim=99, 실물 RPi=22).
#         좌표계는 mapv6 라 sim/실물 동일. 실물 캡처 예: ROS_DOMAIN_ID=22 scripts/capture_waypoint.sh W13
# 방식: /amcl_pose 2회 캡처 → 일치(드리프트<2cm/0.02rad) 확인으로 AMCL 락 안정 점검 후 저장.
# 전제: Nav2/AMCL 가동 + initialpose 설정되어 /amcl_pose 가 발행 중이어야 함.
# NOTE: set -u 금지 — ROS setup.bash 가 미설정 변수(AMENT_TRACE_SETUP_FILES 등) 를 참조함.

ID="${1:-}"
case "$ID" in
  ""|--*) echo "사용법: $(basename "$0") <ID> [--dry-run]   (예: $(basename "$0") W13)"; exit 1;;
esac
DRY=0
[ "${2:-}" = "--dry-run" ] && DRY=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"
YAML="$WS/config/waypoints_mapv6_capture.yaml"
[ -f "$YAML" ] || { echo "FAIL: yaml 없음: $YAML"; exit 1; }

source /opt/ros/jazzy/setup.bash
source "$WS/install/setup.bash" 2>/dev/null

echo "[capture] /amcl_pose 2회 캡처 (ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0})..."
RAW1="$(ros2 topic echo --once /amcl_pose 2>/dev/null)"
RAW2="$(ros2 topic echo --once /amcl_pose 2>/dev/null)"
if [ -z "$RAW1" ] || [ -z "$RAW2" ]; then
  echo "FAIL: /amcl_pose 무발행 — Nav2/AMCL 가동 + initialpose 설정 확인 (도메인도 확인)"
  exit 2
fi

AMCL1="$RAW1" AMCL2="$RAW2" WID="$ID" YAML="$YAML" DRY="$DRY" python3 <<'PYEOF'
import os, re, math, yaml, shutil

def pose_of(raw):
    docs = [d for d in yaml.safe_load_all(raw) if d]
    p = docs[0]["pose"]["pose"]
    x = p["position"]["x"]; y = p["position"]["y"]; q = p["orientation"]
    yaw = math.atan2(2*(q["w"]*q["z"] + q["x"]*q["y"]),
                     1 - 2*(q["y"]*q["y"] + q["z"]*q["z"]))
    return x, y, yaw

wid = os.environ["WID"]
x1, y1, t1 = pose_of(os.environ["AMCL1"])
x2, y2, t2 = pose_of(os.environ["AMCL2"])
drift = max(abs(x1 - x2), abs(y1 - y2), abs(t1 - t2))
stable = drift < 0.02
newline = f"  {wid}: {{x: {x2:.4f}, y: {y2:.4f}, yaw: {t2:.4f}}}"
print(f"[capture] 1회: x={x1:.4f} y={y1:.4f} yaw={t1:.4f}")
print(f"[capture] 2회: x={x2:.4f} y={y2:.4f} yaw={t2:.4f}  (drift={drift:.4f} -> "
      + ("안정" if stable else "불안정! AMCL 미수렴/이동 중일 수 있음, 잠시 후 재실행 권장") + ")")
print(f"[line] {newline}")

if os.environ["DRY"] == "1":
    print("[dry-run] 저장 안 함. 위 [line] 을 yaml 의 waypoints: 블록에 붙여넣어도 됨.")
    raise SystemExit(0)

path = os.environ["YAML"]
lines = open(path, "r", encoding="utf-8").read().splitlines()

# waypoints: 블록 영역 [start, end) — 'waypoints:' 다음부터 다음 최상위 키(예: home:) 전까지
start = next((i + 1 for i, ln in enumerate(lines) if ln.rstrip() == "waypoints:"), None)
if start is None:
    print("FAIL: yaml 에 'waypoints:' 블록 없음 — 수동 추가 필요"); raise SystemExit(4)
end = len(lines)
for i in range(start, len(lines)):
    s = lines[i]
    if s and not s[0].isspace() and not s.lstrip().startswith("#"):
        end = i; break

last_entry, dup = None, None
for i in range(start, end):
    m = re.match(r"^  ([A-Za-z0-9_]+):", lines[i])
    if m:
        last_entry = i
        if m.group(1) == wid:
            dup = i

shutil.copyfile(path, path + ".bak")
if dup is not None:
    lines[dup] = newline
    action = f"갱신(기존 {wid} 덮어씀)"
else:
    ins = (last_entry + 1) if last_entry is not None else start
    lines.insert(ins, newline)
    action = "신규 추가"

open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(f"[save] {action} -> {path}")
print(f"[save] 백업: {path}.bak")
PYEOF
