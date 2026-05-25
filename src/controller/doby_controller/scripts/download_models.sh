#!/usr/bin/env bash
# 모델 자산 다운로드 (Phase 2 W4+).
# .gitignore에 의해 모델 파일은 커밋되지 않으므로, 새 환경/CI에서 1회 실행.
# 멱등 — 이미 있으면 skip.

set -euo pipefail

WS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

declare -A MODELS=(
  ["dobi_npc_emotion/models/face_landmarker.task"]="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
  ["dobi_npc_emotion/models/efficientdet_lite0.tflite"]="https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/1/efficientdet_lite0.tflite"
  ["dobi_npc_minigame/models/gesture_recognizer.task"]="https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
)

for rel_path in "${!MODELS[@]}"; do
  url="${MODELS[$rel_path]}"
  dest="$WS_ROOT/src/dobi_npc/$rel_path"
  dest_dir="$(dirname "$dest")"

  mkdir -p "$dest_dir"

  if [[ -f "$dest" && -s "$dest" ]]; then
    echo "[skip] $rel_path (already $(stat -c %s "$dest") bytes)"
    continue
  fi

  echo "[get ] $rel_path"
  echo "       $url"
  curl --fail --location --progress-bar --output "$dest" "$url"
  echo "[done] $rel_path ($(stat -c %s "$dest") bytes)"
done

echo "[ok  ] all models present"
