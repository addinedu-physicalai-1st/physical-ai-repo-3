#!/usr/bin/env python3
"""tts_node — UtterRequest → 음성 출력 + 완료 신호 + abort 즉시 중단 + dwell.

Phase 2 W4-③+. /dialog/utter (UtterRequest) 구독 → edge-tts mp3 합성 →
pygame.mixer.music 재생 → 완료 시 /dialog/utter_done 발행.
/rapport/event (abort_trigger) 구독 → mixer.stop() 즉시 중단.

정책:
  - interrupt: 새 utter가 들어오면 진행 중 재생 즉시 중단 후 새것 재생.
    합성 도중 stale이 된 결과는 _gen counter로 폐기.
  - utter_done: 100ms ROS Timer로 mixer.get_busy() 폴링.
    busy → not busy 전이 시 std_msgs/Empty 발행. BT의 IceBreak/Offer/LeadIn이
    이 신호를 기다려 SUCCESS 반환 → cafe_funnel 자연스러운 박자.
  - abort: /rapport/event의 event_type=="abort_trigger" 수신 시 mixer.stop()
    + _gen 무효화 + was_busy=False (utter_done 발행 안 함, BT는 halt됨).
  - abort dwell: abort 후 일정 시간(abort_dwell_sec, 기본 2.0s) 새 utter 요청
    무시. face_avatar의 dwell과 대칭. BT halt 직후 race로 지연 도착하는
    persona_manager 발화를 차단해 음성/표정 일관성 유지. 매 abort_trigger
    수신 시 timer reset (sustained abort 동안 dwell 연장).

엔진은 본 노드에 캡슐화. 미래 LLM/TTS 변경 시 본 파일 + persona YAML voice
섹션 + requirements.txt만 갱신. 인터페이스(메시지/토픽) 그대로 유지.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

import edge_tts

# pygame 임포트 시 출력 억제
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame  # noqa: E402

from std_msgs.msg import Empty, String
from dobi_npc_msgs.msg import UtterRequest, RapportEvent


class TtsNode(Node):
    """edge-tts + pygame.mixer 발화 노드 + 완료 신호 + abort 중단."""

    def __init__(self):
        super().__init__('tts_node')

        self.declare_parameter('input_topic', '/dialog/utter')
        self.declare_parameter('done_topic', '/dialog/utter_done')
        self.declare_parameter('rapport_topic', '/rapport/event')
        self.declare_parameter('face_topic', '/face_avatar/expression')
        self.declare_parameter('default_voice', 'ko-KR-SunHiNeural')
        self.declare_parameter('default_rate', '+0%')
        self.declare_parameter('default_pitch', '+0Hz')
        self.declare_parameter('done_poll_hz', 10.0)
        # abort 후 일정 시간 동안 새 utter 무시 (face_avatar dwell과 대칭).
        # 0이면 비활성. 매 abort_trigger 수신 시 reset (sustained abort 연장).
        self.declare_parameter('abort_dwell_sec', 2.0)

        topic = self.get_parameter('input_topic').value
        done_topic = self.get_parameter('done_topic').value
        rapport_topic = self.get_parameter('rapport_topic').value
        face_topic = self.get_parameter('face_topic').value
        self.default_voice = self.get_parameter('default_voice').value
        self.default_rate = self.get_parameter('default_rate').value
        self.default_pitch = self.get_parameter('default_pitch').value
        done_poll_hz = float(self.get_parameter('done_poll_hz').value)
        self.abort_dwell_sec = float(
            self.get_parameter('abort_dwell_sec').value)

        try:
            pygame.mixer.init()
        except pygame.error as e:
            raise RuntimeError(f"pygame.mixer.init 실패: {e}")

        self._tmp_dir = tempfile.mkdtemp(prefix='dobi_npc_tts_')
        self._mp3_path = os.path.join(self._tmp_dir, 'utter.mp3')

        # 동기 상태 (lock 보호 또는 GIL atomic 의존)
        self._lock = threading.Lock()
        self._gen = 0           # 새 utter마다 증가, stale 합성 폐기
        self._was_busy = False  # mixer 재생 중 표시 (utter_done 폴링용)
        # abort dwell — abort 후 이 시각(monotonic)까지 새 utter 무시
        self._dwell_until = 0.0

        # 입력
        self.sub = self.create_subscription(
            UtterRequest, topic, self._on_utter, 10
        )
        self.rapport_sub = self.create_subscription(
            RapportEvent, rapport_topic, self._on_rapport, 10
        )
        # 출력
        self.done_pub = self.create_publisher(Empty, done_topic, 10)
        # face/utter 시작 동기화: persona_manager가 packing한 face_expression을
        # mixer.play 직전에 발행 → face_avatar가 음성과 거의 동시에 표정 전환
        self.face_pub = self.create_publisher(String, face_topic, 10)
        # utter_done 폴링 (100ms)
        self.timer = self.create_timer(1.0 / done_poll_hz, self._check_done)

        self.get_logger().info(
            f"tts_node ready: in={topic} done={done_topic} face={face_topic} "
            f"abort_sub={rapport_topic} default_voice={self.default_voice} "
            f"abort_dwell={self.abort_dwell_sec:.1f}s"
        )

    def _on_utter(self, msg: UtterRequest):
        text = (msg.text or '').strip()
        if not text:
            self.get_logger().warning("빈 text — skip")
            return

        # abort dwell — face_avatar와 대칭. abort 후 race로 지연 도착하는 utter 차단.
        now = time.monotonic()
        if now < self._dwell_until:
            remaining = self._dwell_until - now
            self.get_logger().info(
                f"abort dwell {remaining:.1f}s remaining → ignore "
                f"[{msg.persona_id}/{msg.stage_id}] {text!r}")
            return

        voice = msg.voice or self.default_voice
        rate = msg.rate or self.default_rate
        pitch = msg.pitch or self.default_pitch
        face = (msg.face_expression or '').strip()

        with self._lock:
            self._gen += 1
            my_gen = self._gen

        # interrupt: 진행 중 재생 즉시 중단
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
        # 직전 발화의 done 발행 안 하도록 was_busy 리셋
        # (새 발화의 was_busy=True는 _synth에서 play 직후 set)
        self._was_busy = False

        self.get_logger().info(
            f"speak [{msg.persona_id}/{msg.stage_id}/{voice}/{rate}/{pitch}/"
            f"face={face or '-'}] {text!r}"
        )

        threading.Thread(
            target=self._synth_and_play,
            args=(text, voice, rate, pitch, face, my_gen),
            daemon=True,
        ).start()

    def _on_rapport(self, msg: RapportEvent):
        if msg.event_type != "abort_trigger":
            return
        # dwell timer 갱신 (매 abort_trigger 메시지마다 reset — sustained abort 연장)
        if self.abort_dwell_sec > 0:
            self._dwell_until = time.monotonic() + self.abort_dwell_sec
        # 진행 중 재생 즉시 중단 + 진행 중 합성도 stale 처리
        if pygame.mixer.music.get_busy() or self._was_busy:
            self.get_logger().warning(
                f"abort_trigger ({msg.reason}) → mixer.stop() "
                f"(dwell {self.abort_dwell_sec:.1f}s)")
            try:
                pygame.mixer.music.stop()
            except pygame.error:
                pass
        self._was_busy = False  # utter_done 발행 안 하게
        with self._lock:
            self._gen += 1  # 진행 중 합성 폐기

    def _check_done(self):
        """100ms 폴링. busy → not busy 전이 시 utter_done 발행."""
        busy = pygame.mixer.music.get_busy()
        if self._was_busy and not busy:
            self._was_busy = False
            self.done_pub.publish(Empty())
            self.get_logger().info("utter_done")

    def _synth_and_play(
        self, text: str, voice: str, rate: str, pitch: str,
        face: str, my_gen: int,
    ):
        try:
            asyncio.run(self._synth(text, voice, rate, pitch, face, my_gen))
        except Exception as e:
            self.get_logger().error(f"TTS 실패: {e}")

    async def _synth(
        self, text: str, voice: str, rate: str, pitch: str,
        face: str, my_gen: int,
    ):
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await comm.save(self._mp3_path)
        except Exception as e:
            self.get_logger().error(
                f"edge_tts 합성 실패 (voice={voice}): {e}"
            )
            return

        with self._lock:
            if my_gen != self._gen:
                return  # stale — 후속 utter 또는 abort

        # face/utter 동시 시작: play 직전에 face 발행. 빈 문자열이면 변경 없음
        # (이전 표정 유지). face_avatar는 즉시 표정 전환, mixer.play도 즉시 시작.
        if face:
            face_msg = String()
            face_msg.data = face
            self.face_pub.publish(face_msg)

        try:
            pygame.mixer.music.load(self._mp3_path)
            pygame.mixer.music.play()
            self._was_busy = True  # 폴링이 다음 tick에서 done 감지
        except pygame.error as e:
            self.get_logger().error(f"mp3 재생 실패: {e}")

    def destroy_node(self):
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        try:
            for f in os.listdir(self._tmp_dir):
                os.remove(os.path.join(self._tmp_dir, f))
            os.rmdir(self._tmp_dir)
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = TtsNode()
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
