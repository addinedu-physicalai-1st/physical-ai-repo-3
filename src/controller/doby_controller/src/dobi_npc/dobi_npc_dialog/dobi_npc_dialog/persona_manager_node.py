#!/usr/bin/env python3
"""
persona_manager_node.py
Phase 1 W3 — 페르소나 로드 + 전환 + phrase 발화.

YAML 페르소나(generic 베이스 + 3 자식)를 로드하고:
  - /set_persona (SetPersona) — 페르소나 전환
  - /dialog/request (std_msgs/String) — 단계 ID 받음 ("icebreak" | "offer" | "leadin")
  - /dialog/router_in (UtterRequest) — dialog_router 입력 (source="npc", priority=30)

A1 변경: 직접 /dialog/utter 발행 → /dialog/router_in 으로 변경. 멀티 모드
멀티 publisher 환경에서 dialog_router 가 단일 게이트로 직렬화. tts_node 인터페이스
는 변경 없음 (router 가 /dialog/utter 로 송출).

=== 학술 근거 ===
  - Isla 2005 character hierarchy (페르소나 상속 구조)
  - Castro-González 2016 polite phrase pool

=== 사용 예 ===
  ros2 run dobi_npc_dialog persona_manager
  ros2 service call /set_persona dobi_npc_msgs/srv/SetPersona \\
    "{persona_name: 'casual_browser'}"
  ros2 topic pub --once /dialog/request std_msgs/String "{data: 'icebreak'}"
  ros2 topic echo /dialog/router_in    # 본 노드 출력
  ros2 topic echo /dialog/utter        # router 출력 (tts_node 입력)
"""

import os
import random
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String
from ament_index_python.packages import get_package_share_directory
from dobi_npc_msgs.srv import SetPersona
from dobi_npc_msgs.msg import UtterRequest

import yaml


class PersonaManagerNode(Node):
    def __init__(self):
        super().__init__('persona_manager')

        self.declare_parameter('persona_dir', '')
        self.declare_parameter('default_persona', 'casual_browser')
        self.declare_parameter('language', 'ko')

        persona_dir = self.get_parameter('persona_dir').value
        default_persona = self.get_parameter('default_persona').value
        self.language = self.get_parameter('language').value

        if not persona_dir:
            share = get_package_share_directory('dobi_npc_dialog')
            persona_dir = os.path.join(share, 'config', 'personas')
        self.persona_dir = persona_dir

        self.personas = self._load_all_personas(persona_dir)
        self.get_logger().info(
            f'Loaded {len(self.personas)} personas: '
            f'{sorted(self.personas.keys())}'
        )

        if default_persona not in self.personas:
            self.get_logger().warn(
                f'Default persona "{default_persona}" 미발견 → "generic" 사용')
            default_persona = 'generic'
        self.current_persona_id = default_persona
        self.get_logger().info(f'Current persona: {self.current_persona_id}')

        self.srv_ = self.create_service(
            SetPersona, '/set_persona', self._handle_set_persona)
        self.sub_ = self.create_subscription(
            String, '/dialog/request', self._handle_request, 10)
        # A1: dialog_router 입력으로 송출. router 가 우선순위 큐 + utter_done 동기화로
        # 직렬화 후 /dialog/utter 로 tts_node 에 전달.
        # face_expression 은 UtterRequest 에 packing → tts_node 가 mixer.play 직전
        # /face_avatar/expression 발행 (face/utter 시작 동기화).
        self.pub_ = self.create_publisher(UtterRequest, '/dialog/router_in', 10)

    def _load_all_personas(self, persona_dir):
        """디렉토리 내 모든 yaml 로드 + parent 상속 머지."""
        personas_raw = {}
        path = Path(persona_dir)
        if not path.exists():
            self.get_logger().error(f'Persona dir 없음: {persona_dir}')
            return {}

        for yaml_file in sorted(path.glob('*.yaml')):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                pid = data.get('persona_id')
                if not pid:
                    self.get_logger().warn(
                        f'{yaml_file.name}: persona_id 없음, 무시')
                    continue
                personas_raw[pid] = data
            except Exception as e:
                self.get_logger().error(f'{yaml_file.name} 로드 실패: {e}')

        merged = {}
        for pid in personas_raw:
            merged[pid] = self._resolve_inheritance(pid, personas_raw)
        return merged

    def _resolve_inheritance(self, pid, personas_raw, _visited=None):
        """parent를 재귀적으로 머지."""
        if _visited is None:
            _visited = set()
        if pid in _visited:
            self.get_logger().error(f'순환 상속 감지: {pid}')
            return {}
        _visited.add(pid)

        data = personas_raw.get(pid, {}).copy()
        parent_id = data.pop('parent', None)
        if parent_id and parent_id in personas_raw:
            parent_data = self._resolve_inheritance(
                parent_id, personas_raw, _visited)
            data = self._deep_merge(parent_data, data)
        return data

    def _deep_merge(self, base, override):
        """base 위에 override를 깊이 머지."""
        result = base.copy() if isinstance(base, dict) else {}
        for k, v in override.items():
            if (k in result and isinstance(result[k], dict)
                    and isinstance(v, dict)):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def _handle_set_persona(self, request, response):
        if request.persona_name in self.personas:
            self.current_persona_id = request.persona_name
            response.success = True
            response.current_persona = request.persona_name
            self.get_logger().info(f'Persona 전환: {request.persona_name}')
        else:
            response.success = False
            response.current_persona = self.current_persona_id
            self.get_logger().warn(
                f'Persona 미발견: {request.persona_name} '
                f'(가용: {sorted(self.personas.keys())})')
        return response

    def _handle_request(self, msg):
        stage_id = msg.data

        # phrase + voice + face를 한 UtterRequest로 packing (Phase 2 W4-③+)
        # tts_node가 mixer.play 직전에 face도 발행 → face/utter 시작 동기화
        phrase = self._pick_phrase(stage_id, self.language)
        if phrase is None:
            self.get_logger().warn(
                f'Phrase 없음: persona={self.current_persona_id} '
                f'stage={stage_id} lang={self.language}')
            return

        utter = UtterRequest()
        utter.header.stamp = self.get_clock().now().to_msg()
        utter.text = phrase
        voice = self._pick_voice()
        utter.voice = voice.get('name', 'ko-KR-SunHiNeural')
        utter.rate = voice.get('rate', '+0%')
        utter.pitch = voice.get('pitch', '+0Hz')
        face = self._pick_face_expression(stage_id)
        utter.face_expression = face if face is not None else ''
        utter.persona_id = self.current_persona_id
        utter.stage_id = stage_id
        # A1 라우팅 메타데이터 — NPC 호객은 가장 낮은 우선, preempt 안 함
        utter.source = 'npc'
        utter.priority = 30
        utter.preempt = False
        self.pub_.publish(utter)
        self.get_logger().info(
            f'[{self.current_persona_id}/{stage_id}/{self.language}/'
            f'{utter.voice}/face={utter.face_expression or "-"}] {phrase}')

    def _pick_phrase(self, stage_id, language):
        persona = self.personas.get(self.current_persona_id)
        if not persona:
            return None
        phrases = (persona.get('phrases', {})
                          .get(stage_id, {})
                          .get(language, []))
        if not phrases:
            return None
        return random.choice(phrases)

    def _pick_face_expression(self, stage_id):
        persona = self.personas.get(self.current_persona_id)
        if not persona:
            return None
        return persona.get('face_expression', {}).get(stage_id)

    def _pick_voice(self):
        persona = self.personas.get(self.current_persona_id, {})
        return persona.get('voice', {})


def main(args=None):
    rclpy.init(args=args)
    node = PersonaManagerNode()
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
