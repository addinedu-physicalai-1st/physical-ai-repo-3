#!/usr/bin/env python3
"""
dialog_router_node.py
멀티 모드 → 단일 출력 채널(face/TTS) 직렬화 게이트.

역할:
  - 모든 모드(NPC/서빙/팔로우/운영자/안전)가 /dialog/router_in 에 publish
  - 우선순위 큐 + utter_done 동기화로 직렬화
  - preempt=True 는 큐 head 배치 (현 발화는 utter_done 까지 대기)
  - /dialog/utter 로 직렬화된 발화 송출 (tts_node 입력)

토픽:
  - SUB /dialog/router_in   (dobi_npc_msgs/UtterRequest)
  - SUB /dialog/utter_done  (std_msgs/Empty)
  - PUB /dialog/utter       (dobi_npc_msgs/UtterRequest)

우선순위 정책 (낮을수록 우선):
  0   safety  alarm
  10  operator 강제 발화
  20  serving 안내
  30  npc    호객 (default)
  255 (lowest)

preempt 정책 (현재 cut):
  - True  → 큐 head 배치, 즉시 다음 dispatch 시 우선
  - 현 발화 즉시 중단(audio cut)은 미구현 — tts_node /dialog/cancel 추가 후 확장
  - 안전 alarm 즉시 중단은 별도 rapport abort_trigger 경로 (tts_node 자체 처리)

큐 안정성:
  - heap key = (effective_priority, seq) — seq 단조 증가로 타이브레이크 FIFO
  - effective_priority = -1 if preempt else priority

라이프사이클:
  - on_request: heap push → dispatch
  - on_utter_done: playing=False → dispatch
  - dispatch: not playing AND heap nonempty 시 1건 pop+publish

사용:
  ros2 run dobi_npc_dialog dialog_router
  ros2 topic pub --once /dialog/router_in dobi_npc_msgs/msg/UtterRequest \\
    "{text: '테스트', source: 'operator', priority: 10, preempt: true,
      voice: 'ko-KR-SunHiNeural', rate: '+0%', pitch: '+0Hz'}"
"""

import heapq
import threading

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import Empty
from dobi_npc_msgs.msg import UtterRequest


PREEMPT_KEY = -1  # 모든 일반 priority(0~255) 보다 우선


class DialogRouterNode(Node):
    """단일 출력 채널 게이트 — 우선순위 큐 + utter_done 동기화."""

    def __init__(self):
        super().__init__('dialog_router')

        self.declare_parameter('input_topic', '/dialog/router_in')
        self.declare_parameter('output_topic', '/dialog/utter')
        self.declare_parameter('done_topic', '/dialog/utter_done')
        self.declare_parameter('queue_warn_size', 10)

        in_topic = self.get_parameter('input_topic').value
        out_topic = self.get_parameter('output_topic').value
        done_topic = self.get_parameter('done_topic').value
        self.queue_warn_size = int(self.get_parameter('queue_warn_size').value)

        self._lock = threading.Lock()
        self._heap = []      # (effective_priority, seq, msg)
        self._seq = 0        # 단조 증가 — heap 타이브레이크 + msg 비교 회피
        self._playing = False

        self.sub_in = self.create_subscription(
            UtterRequest, in_topic, self._on_request, 10)
        self.sub_done = self.create_subscription(
            Empty, done_topic, self._on_done, 10)
        self.pub_out = self.create_publisher(UtterRequest, out_topic, 10)

        self.get_logger().info(
            f'dialog_router ready: in={in_topic} out={out_topic} '
            f'done={done_topic}')

    def _label(self, msg: UtterRequest) -> str:
        """로그 라벨 — 디버깅 추적용."""
        src = msg.source or '?'
        prio = msg.priority
        pre = 'P' if msg.preempt else ' '
        text_short = (msg.text or '')[:30]
        return f"[{src}/p={prio}/{pre}] '{text_short}'"

    def _on_request(self, msg: UtterRequest):
        eff_prio = PREEMPT_KEY if msg.preempt else int(msg.priority)
        with self._lock:
            self._seq += 1
            heapq.heappush(self._heap, (eff_prio, self._seq, msg))
            qsize = len(self._heap)
            playing = self._playing
        self.get_logger().info(
            f'enqueue {self._label(msg)} eff_prio={eff_prio} '
            f'qsize={qsize} playing={playing}')
        if qsize >= self.queue_warn_size:
            self.get_logger().warn(
                f'router queue 누적 {qsize} — backpressure 점검 필요')
        self._dispatch()

    def _on_done(self, _msg):
        with self._lock:
            self._playing = False
            qsize = len(self._heap)
        self.get_logger().info(f'utter_done → playing=False qsize={qsize}')
        self._dispatch()

    def _dispatch(self):
        with self._lock:
            if self._playing or not self._heap:
                return
            eff_prio, seq, msg = heapq.heappop(self._heap)
            self._playing = True
        self.pub_out.publish(msg)
        self.get_logger().info(
            f'dispatch {self._label(msg)} eff_prio={eff_prio} seq={seq}')


def main(args=None):
    rclpy.init(args=args)
    node = DialogRouterNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
