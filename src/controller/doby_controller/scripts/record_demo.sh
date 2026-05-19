#!/bin/bash
# record_demo.sh — Gazebo + dashboard 분할 화면 풀스크린 녹화 + 5 모드 자동 시나리오.
#
# 사용:
#   1. run_sim.sh 가 떠 있고 (Gazebo + Nav2 + dashboard), mode=idle 상태.
#   2. 사용자가 화면 layout 잡음 — Gazebo GUI + 브라우저 dashboard 분할.
#   3. bash scripts/record_demo.sh
#   4. 5초 카운트다운 → 녹화 시작 → 시나리오 자동 → 종료.
#
# 출력: ~/moca/recordings/demo_YYYYMMDD_HHMMSS.mp4
#
# 옵션:
#   --resolution=1920x1080  (default — 풀스크린)
#   --offset=0,0             (캡처 좌상단)
#   --framerate=30           (default)
#   --no-countdown           (즉시 시작)

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"

RES="1920x1080"
OFFSET="0,0"
FPS=30
COUNTDOWN=5
for arg in "$@"; do
    case "$arg" in
        --resolution=*) RES="${arg#--resolution=}" ;;
        --offset=*)     OFFSET="${arg#--offset=}" ;;
        --framerate=*)  FPS="${arg#--framerate=}" ;;
        --no-countdown) COUNTDOWN=0 ;;
        -h|--help)
            grep "^# " "$0" | sed 's/^# //'; exit 0 ;;
    esac
done

# 사전 검증 — dashboard alive + Gazebo + ffmpeg
command -v ffmpeg >/dev/null || { echo "ffmpeg 미설치"; exit 1; }
curl -sf http://localhost:8800/api/v1/health >/dev/null || {
    echo "⚠ dashboard 미가동 — bash scripts/run_sim.sh --no-rviz 먼저 실행"; exit 1; }
pgrep -f "gz sim -r -s" >/dev/null || {
    echo "⚠ Gazebo 미가동 — run_sim.sh 재기동 또는 단순 dashboard 녹화 시 --offset 조정"; }

OUT_DIR="$WS/recordings"
mkdir -p "$OUT_DIR"
TS=$(date +%Y%m%d_%H%M%S)
OUT="$OUT_DIR/demo_${TS}.mp4"

echo "================================================="
echo "  MoCa 5 모드 데모 영상 녹화"
echo "================================================="
echo "  화면      : ${RES} from :0.0+${OFFSET}"
echo "  framerate : ${FPS}fps"
echo "  출력      : $OUT"
echo "================================================="

if [ "$COUNTDOWN" -gt 0 ]; then
    echo
    echo "  ★ 화면 layout 준비 (Gazebo + dashboard 분할 권장)"
    echo "    Ctrl+C 로 취소 가능"
    for i in $(seq "$COUNTDOWN" -1 1); do
        printf "  녹화 시작 %ds 전 ...\r" "$i"
        sleep 1
    done
    echo
fi

echo "▶ 녹화 시작 — $(date +%H:%M:%S)"

# x11grab 백그라운드. ultrafast preset + crf 23 → 인코딩 부하 ↓, 5분 영상 ~200-400MB.
ffmpeg -y -hide_banner -loglevel warning \
    -f x11grab -framerate "$FPS" -video_size "$RES" -i ":0.0+${OFFSET}" \
    -c:v libx264 -preset ultrafast -crf 23 -pix_fmt yuv420p \
    "$OUT" &
FFPID=$!

# 종료 안전망 — INT/TERM/EXIT 시 ffmpeg 정상 종료
cleanup() {
    if kill -0 "$FFPID" 2>/dev/null; then
        echo "■ ffmpeg 종료 (SIGINT) ..."
        kill -INT "$FFPID" 2>/dev/null || true
        wait "$FFPID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

sleep 2     # ffmpeg warmup

# 시나리오 자동 실행
bash "$SCRIPT_DIR/run_demo_scenario.sh"

# 시나리오 후 5초 더 녹화 (자막/엔딩 여유)
echo "▶ 엔딩 5s 여유 녹화 ..."
sleep 5

cleanup
trap - EXIT INT TERM

echo
echo "✓ 녹화 완료: $OUT"
echo "  크기: $(du -h "$OUT" | cut -f1)"
echo "  길이: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT" 2>/dev/null)s"
echo
echo "  재생: xdg-open '$OUT'  또는  vlc '$OUT'"
