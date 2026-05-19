#!/usr/bin/env python3
"""follow_tuner.py — follow_controller 라이브 튜닝 GUI.

화면:
  ┌─────────────────────────┐
  │   /robot_cam/image_raw  │   (compressed → PIL 변환, ~10Hz refresh)
  │                         │
  ├─────────────────────────┤
  │ max_linear   [────●──]  │   <─ 슬라이더 즉시 ros2 param set
  │ max_angular  [──●────]  │
  │ kp_linear    [──●────]  │
  │ kp_angular   [────●──]  │
  └─────────────────────────┘

전제:
  - follow_controller 가 add_on_set_parameters_callback 으로 라이브 갱신 지원.
  - SetParameters 서비스 = /follow_controller/set_parameters
  - 이미지 토픽 = /robot_cam/image_raw/compressed (sub 0 인 raw 가 아니라 compressed
    → Wi-Fi 부담 ↓)

실행 (워크스페이스 루트에서):
  source /opt/ros/jazzy/setup.bash
  source install/setup.bash  # (의존 없이 standalone 도 가능)
  python3 scripts/follow_tuner.py
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk

import cv2
import numpy as np
import rclpy
from PIL import Image, ImageTk
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import SetParameters
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


SLIDER_CONFIG = [
    # name, min, max, init, resolution
    ('max_linear',  0.0,  1.0,   0.4, 0.05),
    ('max_angular', 0.0,  2.0,   0.6, 0.05),
    ('kp_linear',  -2.0,  2.0,  -0.8, 0.05),
    ('kp_angular',  0.0,  3.0,   1.2, 0.05),
]

PARAM_SVC = '/follow_controller/set_parameters'
IMAGE_TOPIC = '/robot_cam/image_raw/compressed'


class TunerNode(Node):
    def __init__(self, frame_q: queue.Queue):
        super().__init__('follow_tuner')
        self.frame_q = frame_q
        # BEST_EFFORT QoS — sub 가 ACK 안 보냄 → pub (RELIABLE) 재전송 큐 안 쌓임.
        # Wi-Fi packet loss burst stall 회피 (2026-05-07).
        self.sub = self.create_subscription(
            CompressedImage, IMAGE_TOPIC, self._on_image,
            qos_profile_sensor_data)
        self.param_cli = self.create_client(SetParameters, PARAM_SVC)

    def _on_image(self, msg: CompressedImage):
        try:
            buf = np.frombuffer(msg.data, dtype=np.uint8)
            bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if bgr is None:
                return
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            # drop-oldest queue
            while not self.frame_q.empty():
                try:
                    self.frame_q.get_nowait()
                except queue.Empty:
                    break
            self.frame_q.put_nowait(rgb)
        except (queue.Full, Exception) as e:
            self.get_logger().warning(f"decode/queue err: {e}")

    def set_param(self, name: str, value: float):
        if not self.param_cli.service_is_ready():
            return
        req = SetParameters.Request()
        p = Parameter()
        p.name = name
        v = ParameterValue()
        v.type = ParameterType.PARAMETER_DOUBLE
        v.double_value = float(value)
        p.value = v
        req.parameters.append(p)
        self.param_cli.call_async(req)


def build_gui(node: TunerNode, frame_q: queue.Queue):
    root = tk.Tk()
    root.title("follow_tuner — robot_cam + 라이브 게인")

    # 화면 영역
    img_label = tk.Label(root, bg='black', width=640, height=480)
    img_label.pack(padx=8, pady=8)

    # 상태 표시줄
    status = tk.StringVar(value="…")
    tk.Label(root, textvariable=status, anchor='w', fg='gray').pack(fill='x', padx=8)

    # 슬라이더 영역
    slider_frame = tk.Frame(root)
    slider_frame.pack(fill='x', padx=8, pady=8)

    def make_cb(name):
        # tkinter Scale 콜백은 string 으로 들어옴
        return lambda v: node.set_param(name, float(v))

    for name, lo, hi, init, step in SLIDER_CONFIG:
        row = tk.Frame(slider_frame)
        row.pack(fill='x', pady=2)
        tk.Label(row, text=name, width=14, anchor='w').pack(side='left')
        s = tk.Scale(row, from_=lo, to=hi, resolution=step,
                     orient='horizontal', length=480,
                     command=make_cb(name))
        s.set(init)
        s.pack(side='left', fill='x', expand=True)

    # 이미지 갱신 루프 (main thread, tkinter)
    def refresh():
        rgb = None
        try:
            while True:
                rgb = frame_q.get_nowait()
        except queue.Empty:
            pass
        if rgb is not None:
            try:
                pil = Image.fromarray(rgb)
                tkimg = ImageTk.PhotoImage(pil)
                img_label.configure(image=tkimg, width=pil.width, height=pil.height)
                img_label.image = tkimg
                ready = (
                    node.param_cli.service_is_ready()
                    if node.param_cli is not None else False
                )
                status.set(f"image {pil.width}x{pil.height}  "
                           f"param_svc={'ready' if ready else 'wait'}")
            except Exception as e:
                status.set(f"draw err: {e}")
        root.after(50, refresh)

    refresh()
    return root


def main():
    rclpy.init()
    frame_q: queue.Queue = queue.Queue(maxsize=2)
    node = TunerNode(frame_q)

    spin_t = threading.Thread(target=lambda: rclpy.spin(node), daemon=True)
    spin_t.start()

    root = build_gui(node, frame_q)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
