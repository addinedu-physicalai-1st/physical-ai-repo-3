#!/usr/bin/env python3
"""calibrate_follow.py — follow_controller target_height_ratio 라이브 캘리브.

`/robot_cam/persons` (vision_msgs/Detection2DArray)를 구독해 가장 큰 person bbox의
height 비율(bbox_h / image_h)을 롤링 통계로 출력한다. 사용자가 원하는 follow 거리에
서서 안정 값이 잡히면 그 값을 follow_controller의 `target_height_ratio` 파라미터로
넣으면 된다.

사용법:
  1) 사전 조건:
     bash scripts/run_robot_cam.sh                     # RPi 카메라
     ros2 run dobi_npc_emotion person_detector         # 검출 노드 (또는 mode_follow 띄워둔 상태)
  2) 실행:
     python3 scripts/calibrate_follow.py [--image-height 480] [--window 5.0]
  3) 사용자가 원하는 follow 거리에 서서 화면에 한 명만 보이게.
  4) 1초마다 mean / std / N 출력 → 안정되면 Ctrl-C → 최종 추천값.

기본 정책:
  - 가장 큰 bbox 1개만 선택 (다인 시야는 가장 가까운 사람 가정)
  - 마지막 N초(기본 5)의 샘플로 통계
  - bbox_h 안 잡히는 frame은 무시 (검출 0인 frame은 통계에서 제외)
  - image_height는 기본 480 (run_robot_cam.sh 기본값). 실 카메라 해상도 다르면 지정.

target_height_ratio 의 의미:
  - 1.0 = bbox 높이가 frame 전체 (사람이 매우 가까움, ~50cm 이내)
  - 0.5 = 50% (성인 전신 ~2m 거리)
  - 0.25 = 25% (~4m)
  - 0.1 = 10% (~5~6m, GEFA 원거리 한계)

본 스크립트는 follow_controller를 띄우지 않으며 cmd_vel 발행도 안 함 — 안전.
"""
from __future__ import annotations

import argparse
import statistics
import time
from collections import deque

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from vision_msgs.msg import Detection2DArray


class FollowCalibrator(Node):
    def __init__(self, image_h: int, window_sec: float, persons_topic: str):
        super().__init__('follow_calibrator')

        self.image_h = int(image_h)
        self.window_sec = float(window_sec)
        self.samples: deque[tuple[float, float]] = deque()  # 롤링 윈도우 (timestamp, ratio)
        self.all_ratios: list[float] = []                    # 전체 누적 (final_summary용)
        self.frames_total = 0
        self.frames_with_person = 0
        self._last_print = time.monotonic()

        self.sub = self.create_subscription(
            Detection2DArray, persons_topic, self._on_persons, 10)

        # 1초 타이머로 통계 출력
        self.timer = self.create_timer(1.0, self._print_stats)

        self.get_logger().info(
            f"calibrator ready: subscribe={persons_topic} "
            f"image_h={self.image_h} window={self.window_sec:.1f}s"
        )
        self.get_logger().info(
            "사람이 원하는 follow 거리에 서서 안정 값 잡히면 Ctrl-C."
        )

    def _on_persons(self, msg: Detection2DArray):
        self.frames_total += 1
        if not msg.detections:
            return

        # 가장 큰 bbox 1개
        biggest_h = 0.0
        for d in msg.detections:
            if d.bbox.size_y > biggest_h:
                biggest_h = float(d.bbox.size_y)

        if biggest_h <= 0:
            return

        ratio = biggest_h / max(1, self.image_h)
        ts = time.monotonic()
        self.samples.append((ts, ratio))
        self.all_ratios.append(ratio)
        self._trim_window(ts)
        self.frames_with_person += 1

    def _trim_window(self, now: float):
        cutoff = now - self.window_sec
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def _print_stats(self):
        now = time.monotonic()
        self._trim_window(now)

        n = len(self.samples)
        if n == 0:
            self.get_logger().info(
                f"검출 없음 — frames={self.frames_total} "
                f"(person_detector 띄워져 있는지, 사람이 frame 안에 있는지 확인)"
            )
            return

        ratios = [r for _, r in self.samples]
        mean = statistics.mean(ratios)
        stdv = statistics.stdev(ratios) if n > 1 else 0.0
        lo = min(ratios)
        hi = max(ratios)

        approx_dist = self._ratio_to_distance_hint(mean)

        self.get_logger().info(
            f"window={self.window_sec:.0f}s N={n} "
            f"mean={mean:.3f} std={stdv:.3f} "
            f"min={lo:.3f} max={hi:.3f} "
            f"|hint≈{approx_dist}"
        )

    @staticmethod
    def _ratio_to_distance_hint(ratio: float) -> str:
        """bbox_h_ratio → 거리 hint (carbohydrate, calibrated 아님)."""
        if ratio >= 0.85:
            return "<0.7m (매우 가까움)"
        if ratio >= 0.6:
            return "0.7~1.2m"
        if ratio >= 0.4:
            return "1.2~2m"
        if ratio >= 0.25:
            return "2~3m"
        if ratio >= 0.15:
            return "3~5m"
        return ">5m (원거리)"

    def final_summary(self):
        # Ctrl-C 시 두 통계: 마지막 윈도우(권장) + 전체 누적(fallback)
        recent = [r for _, r in self.samples]
        all_ratios = self.all_ratios

        print()
        print("=" * 64)
        print(f" 캘리브 결과")
        print("=" * 64)
        print(f" 전체 frames          : {self.frames_total}")
        print(f" person 검출 frames   : {self.frames_with_person}")
        print()

        if not all_ratios:
            print(" 샘플 0개 — 사람이 한 번도 frame 안에 없었거나 person_detector 미동작.")
            print(" 점검: ros2 topic echo /robot_cam/persons --once")
            print("=" * 64)
            return

        all_mean = statistics.mean(all_ratios)
        all_std = statistics.stdev(all_ratios) if len(all_ratios) > 1 else 0.0

        if recent:
            recent_mean = statistics.mean(recent)
            recent_std = statistics.stdev(recent) if len(recent) > 1 else 0.0
            print(f" [마지막 {self.window_sec:.0f}초 윈도우]  N={len(recent)}  "
                  f"mean={recent_mean:.3f}  std={recent_std:.3f}  "
                  f"(권장 — 안정 시점)")
        else:
            recent_mean = None
            print(f" [마지막 {self.window_sec:.0f}초 윈도우]  N=0  "
                  f"(Ctrl-C 시점에 사람 frame 없음)")
        print(f" [전체 누적]                N={len(all_ratios)}  "
              f"mean={all_mean:.3f}  std={all_std:.3f}  range="
              f"{min(all_ratios):.3f}~{max(all_ratios):.3f}")
        print()

        # 추천값 — 윈도우가 있으면 그것, 아니면 누적 평균
        recommend = recent_mean if recent_mean is not None else all_mean
        print(f" 거리 hint            : {self._ratio_to_distance_hint(recommend)}")
        print()
        print(" 권장 target_height_ratio:  {:.2f}".format(recommend))
        print()
        print(" 적용: mode_follow.launch.py 의 follow_controller parameters에 추가:")
        print("     parameters=[{")
        print(f"         'target_height_ratio': {recommend:.2f},")
        print("         # ... 기타 ...")
        print("     }]")
        print("=" * 64)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--image-height', type=int, default=480,
                    help='카메라 영상 height (px). run_robot_cam.sh 기본 480.')
    ap.add_argument('--window', type=float, default=5.0,
                    help='롤링 통계 윈도우 (초)')
    ap.add_argument('--topic', type=str, default='/robot_cam/persons',
                    help='Detection2DArray 토픽')
    args = ap.parse_args()

    rclpy.init()
    node = FollowCalibrator(
        image_h=args.image_height,
        window_sec=args.window,
        persons_topic=args.topic,
    )
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.final_summary()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
