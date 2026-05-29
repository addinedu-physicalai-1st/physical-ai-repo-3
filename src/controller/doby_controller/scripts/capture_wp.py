#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""capture_wp.py — 현재 로봇 pose(map->base_footprint TF)를 waypoint 로 캡처.

사용 (ROS_DOMAIN_ID=22 + nav2/amcl active 상태에서):
    source /opt/ros/jazzy/setup.bash
    export ROS_DOMAIN_ID=22
    python3 scripts/capture_wp.py W13            # 캡처 + yaml 라인 출력 (저장 X)
    python3 scripts/capture_wp.py W13 --save      # config/waypoints_mapv6_capture.yaml 에 추가/덮어쓰기
    python3 scripts/capture_wp.py HOME --save --section home

안정성: map->base_footprint 를 4회 읽어 spread 출력. spread 가 크면(>0.05m 또는 >2deg)
정지 상태 AMCL 불안정 신호 → 재초기화(2D Pose Estimate) 후 재캡처 권장.
"""
import argparse
import math
import os
import sys
import time

try:
    import argcomplete
except ImportError:
    argcomplete = None

DEFAULT_YAML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "waypoints_mapv6_capture.yaml",
)


def capture(samples: int, timeout: float):
    import rclpy
    from rclpy.duration import Duration
    from rclpy.node import Node
    from rclpy.time import Time
    from tf2_ros import Buffer, TransformListener

    rclpy.init()
    node = Node("capture_wp")
    buf = Buffer(cache_time=Duration(seconds=10.0))
    TransformListener(buf, node)
    xs, ys, yaws = [], [], []
    t0 = time.time()
    while time.time() - t0 < timeout and len(xs) < samples:
        rclpy.spin_once(node, timeout_sec=0.1)
        if buf.can_transform("map", "base_footprint", Time()):
            tf = buf.lookup_transform("map", "base_footprint", Time())
            t, q = tf.transform.translation, tf.transform.rotation
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y),
                             1 - 2 * (q.y ** 2 + q.z ** 2))
            xs.append(t.x); ys.append(t.y); yaws.append(yaw)
            time.sleep(1.0)
    node.destroy_node()
    rclpy.shutdown()
    return xs, ys, yaws


def main():
    p = argparse.ArgumentParser(description="현재 로봇 pose 를 waypoint 로 캡처")
    p.add_argument("label", help="waypoint 라벨 (예: W13, T01, HOME)")
    p.add_argument("--save", action="store_true",
                   help="yaml 에 추가/덮어쓰기 (미지정 시 라인만 출력)")
    p.add_argument("--section", choices=["waypoints", "home", "tables"],
                   default="waypoints", help="yaml 섹션 (default: waypoints)")
    p.add_argument("--yaml", default=DEFAULT_YAML, help="대상 yaml 경로")
    p.add_argument("--samples", type=int, default=4, help="안정성 샘플 수")
    p.add_argument("--timeout", type=float, default=20.0, help="TF 대기 한도(s)")
    if argcomplete:
        argcomplete.autocomplete(p)
    a = p.parse_args()

    xs, ys, yaws = capture(a.samples, a.timeout)
    if not xs:
        print("[ERR] TF map->base_footprint 미수신 — nav2/amcl active + 2D Pose Estimate 확인", file=sys.stderr)
        sys.exit(1)

    x, y, yaw = xs[-1], ys[-1], yaws[-1]
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    dyaw = math.degrees(max(yaws) - min(yaws))
    stable = dx <= 0.05 and dy <= 0.05 and dyaw <= 2.0
    print("  %s: x=%.4f y=%.4f yaw=%.4f rad (%.2f deg)" % (a.label, x, y, yaw, math.degrees(yaw)))
    print("  spread: dx=%.3f dy=%.3f dyaw=%.2f deg  -> %s" %
          (dx, dy, dyaw, "안정" if stable else "⚠ 불안정 (재초기화 권장)"))
    line = "  %s: {x: %.4f, y: %.4f, yaw: %.4f}" % (a.label, x, y, yaw)
    print("  yaml: " + line.strip())

    if not a.save:
        print("  (--save 미지정 — 저장 안 함. 위 yaml 라인 직접 붙여넣기)")
        return
    if not stable:
        print("[WARN] 불안정값 — --save 했지만 재확인 권장", file=sys.stderr)

    # 같은 라벨 있으면 덮어쓰기, 없으면 섹션 끝에 추가
    with open(a.yaml) as f:
        lines = f.readlines()
    key = a.label + ":"
    replaced = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith(key):
            lines[i] = line + "\n"
            replaced = True
            break
    if not replaced:
        lines.append(line + "\n")
    with open(a.yaml, "w") as f:
        f.writelines(lines)
    print("  %s -> %s (%s)" % ("덮어씀" if replaced else "추가", a.yaml, "저장 완료"))


if __name__ == "__main__":
    main()
