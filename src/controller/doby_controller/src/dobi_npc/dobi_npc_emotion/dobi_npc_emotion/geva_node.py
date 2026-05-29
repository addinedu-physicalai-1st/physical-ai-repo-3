#!/usr/bin/env python3
"""GEVA — Gesture/Expression Vision Analyzer (얼굴 표정 → V·A).

Phase 2 W4. EyeCon v3.5 vision.py + analyzer._classify_emotion 포팅.

파이프라인:
  1) cv2.VideoCapture(camera_index)로 노트북 웹캠 1프레임 캡처
  2) MediaPipe FaceLandmarker (IMAGE 모드, output_face_blendshapes=True)
  3) Blendshapes 규칙 엔진으로 7감정 점수(softmax)
  4) Russell circumplex 좌표(Posner 2005 근사)로 가중평균 → (V, A)
  5) /emotion/state (dobi_npc_msgs/EmotionState) 발행

Source 필드: "face". Phase 2 후속 GEFA(자세/접근/회피)와 decision_rule_node에서
Salichs 2014 fusion으로 합쳐진다.
"""
from __future__ import annotations

import os
import time

import cv2
import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

from dobi_npc_msgs.msg import EmotionState


EMOTIONS = ["happy", "sad", "angry", "surprise", "fear", "disgust", "neutral"]

# Russell 1980 circumplex 좌표 (Posner 2005 근사). V=valence, A=arousal.
# CLAUDE.md §2 abort 트리거(V<-0.5, A>0.4)에 angry/fear가 들어가도록 배치.
EMOTION_VA = {
    "happy":    (+0.8, +0.5),
    "sad":      (-0.7, -0.4),
    "angry":    (-0.6, +0.7),
    "surprise": (+0.2, +0.8),
    "fear":     (-0.7, +0.6),
    "disgust":  (-0.7, +0.2),
    "neutral":  (0.0,  0.0),
}


def classify_emotion_from_blendshapes(bs: dict) -> dict:
    """EyeCon analyzer._classify_emotion 포팅.

    bs: {category_name: score} (52 Blendshapes).
    return: 정규화된 7감정 점수 dict.
    """
    scores = {e: 0.0 for e in EMOTIONS}
    if not bs:
        scores["neutral"] = 1.0
        return scores

    smile_l = bs.get("mouthSmileLeft", 0.0)
    smile_r = bs.get("mouthSmileRight", 0.0)
    cheek_l = bs.get("cheekSquintLeft", 0.0)
    cheek_r = bs.get("cheekSquintRight", 0.0)
    scores["happy"] = (smile_l + smile_r) / 2 * 0.6 + (cheek_l + cheek_r) / 2 * 0.4

    frown_l = bs.get("mouthFrownLeft", 0.0)
    frown_r = bs.get("mouthFrownRight", 0.0)
    brow_inner = bs.get("browInnerUp", 0.0)
    scores["sad"] = (frown_l + frown_r) / 2 * 0.5 + brow_inner * 0.5

    brow_down_l = bs.get("browDownLeft", 0.0)
    brow_down_r = bs.get("browDownRight", 0.0)
    mouth_press_l = bs.get("mouthPressLeft", 0.0)
    mouth_press_r = bs.get("mouthPressRight", 0.0)
    jaw_clench = bs.get("jawForward", 0.0)
    scores["angry"] = (
        (brow_down_l + brow_down_r) / 2 * 0.4
        + (mouth_press_l + mouth_press_r) / 2 * 0.3
        + jaw_clench * 0.3
    )

    eye_wide_l = bs.get("eyeWideLeft", 0.0)
    eye_wide_r = bs.get("eyeWideRight", 0.0)
    brow_outer_l = bs.get("browOuterUpLeft", 0.0)
    brow_outer_r = bs.get("browOuterUpRight", 0.0)
    jaw_open = bs.get("jawOpen", 0.0)
    scores["surprise"] = (
        (eye_wide_l + eye_wide_r) / 2 * 0.3
        + brow_inner * 0.2
        + (brow_outer_l + brow_outer_r) / 2 * 0.2
        + jaw_open * 0.3
    )

    lip_press = (mouth_press_l + mouth_press_r) / 2
    scores["fear"] = (
        brow_inner * 0.3
        + (eye_wide_l + eye_wide_r) / 2 * 0.3
        + (mouth_press_l + mouth_press_r) / 2 * 0.2
        + lip_press * 0.2
    )

    nose_l = bs.get("noseSneerLeft", 0.0)
    nose_r = bs.get("noseSneerRight", 0.0)
    upper_lip = bs.get("mouthShrugUpper", 0.0)
    scores["disgust"] = (
        (nose_l + nose_r) / 2 * 0.5
        + upper_lip * 0.3
        + (frown_l + frown_r) / 2 * 0.2
    )

    max_others = max(scores[e] for e in EMOTIONS if e != "neutral")
    scores["neutral"] = max(0.0, 0.5 - max_others)

    total = sum(scores.values())
    if total > 0:
        scores = {k: v / total for k, v in scores.items()}
    else:
        scores["neutral"] = 1.0
    return scores


def emotion_scores_to_va(scores: dict) -> tuple[float, float, float]:
    """7감정 점수의 가중평균 → (V, A, top_score). top_score는 confidence로 쓴다."""
    v = sum(scores[e] * EMOTION_VA[e][0] for e in EMOTIONS)
    a = sum(scores[e] * EMOTION_VA[e][1] for e in EMOTIONS)
    top = max(scores.values())
    return float(np.clip(v, -1.0, 1.0)), float(np.clip(a, -1.0, 1.0)), float(top)


class GevaNode(Node):
    """GEVA 노드 — 노트북 웹캠 → 표정 → V·A → /emotion/state."""

    def __init__(self):
        super().__init__('geva_node')

        self.declare_parameter('camera_index', 0)
        self.declare_parameter('image_topic', '')  # 비우면 camera_index 웹캠 직접; 설정 시 해당 Image 토픽 구독
        self.declare_parameter('publish_rate_hz', 10.0)
        self.declare_parameter('model_path', '')  # 비우면 share/models/face_landmarker.task
        self.declare_parameter('min_detection_confidence', 0.5)
        self.declare_parameter('min_tracking_confidence', 0.5)
        # 카메라 분리 (2026-05-06): 게임은 카메라 3 (외장 RPC-20F) 별도
        # 점유 → GEVA 가 카메라 1 (내장) 을 게임 중에도 그대로 보유. 따라서
        # /geva/suspend|resume 인터페이스 폐기. 단일 카메라로 회귀할 일이
        # 생기면 git history 의 suspend/resume 패턴 (~2026-05-05) 복원.

        self._camera_index = self.get_parameter('camera_index').value
        self._image_topic = self.get_parameter('image_topic').value
        publish_rate_hz = float(self.get_parameter('publish_rate_hz').value)
        model_path = self.get_parameter('model_path').value or self._default_model_path()
        min_det = float(self.get_parameter('min_detection_confidence').value)
        min_trk = float(self.get_parameter('min_tracking_confidence').value)

        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f"FaceLandmarker 모델이 없음: {model_path}. "
                f"`scripts/download_models.sh` 실행 필요."
            )

        self.cap = None
        self._latest_frame = None
        self._sub = None
        if self._image_topic:
            self._bridge = CvBridge()
            self._sub = self.create_subscription(
                Image, self._image_topic, self._on_image, 10)
            self.get_logger().info(
                f"이미지 토픽 구독: {self._image_topic} (카메라 직접 열지 않음)")
        else:
            self.cap = cv2.VideoCapture(self._camera_index)
            if not self.cap.isOpened():
                raise RuntimeError(f"웹캠 열기 실패: index={self._camera_index}")
            self.get_logger().info(
                f"웹캠 열림 (index={self._camera_index}) — "
                f"{int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
                f"{int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
            )

        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = mp_vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=min_det,
            min_face_presence_confidence=min_trk,
            min_tracking_confidence=min_trk,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=False,
        )
        self.landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        self.get_logger().info("FaceLandmarker 초기화 완료 (Blendshapes ON)")

        self.pub = self.create_publisher(EmotionState, '/emotion/state', 10)
        self.timer = self.create_timer(1.0 / publish_rate_hz, self._tick)

        self._frames = 0
        self._faces_detected = 0
        self._last_log = time.time()

    @staticmethod
    def _default_model_path() -> str:
        share = get_package_share_directory('dobi_npc_emotion')
        return os.path.join(share, 'models', 'face_landmarker.task')

    def _on_image(self, msg):
        try:
            self._latest_frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().warning(f"imgmsg_to_cv2 실패: {e}")

    def _tick(self):
        if self._image_topic:
            frame = self._latest_frame
            if frame is None:
                return
        else:
            if self.cap is None:
                return
            ok, frame = self.cap.read()
            if not ok:
                self.get_logger().warning("웹캠 read 실패")
                return
        self._frames += 1

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        try:
            result = self.landmarker.detect(mp_image)
        except Exception as e:
            self.get_logger().warning(f"FaceLandmarker.detect 실패: {e}")
            return

        msg = EmotionState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera_laptop"
        msg.source = "face"

        if not result.face_landmarks or not result.face_blendshapes:
            msg.valence = 0.0
            msg.arousal = 0.0
            msg.confidence = 0.0
            msg.flags = ["no_face"]
            self.pub.publish(msg)
            self._maybe_log()
            return

        self._faces_detected += 1
        bs = {cat.category_name: cat.score for cat in result.face_blendshapes[0]}
        scores = classify_emotion_from_blendshapes(bs)
        v, a, top = emotion_scores_to_va(scores)
        top_emotion = max(scores, key=scores.get)

        msg.valence = v
        msg.arousal = a
        msg.confidence = top
        msg.flags = [f"top:{top_emotion}"]
        self.pub.publish(msg)
        self._maybe_log()

    def _maybe_log(self):
        now = time.time()
        if now - self._last_log >= 5.0:
            rate = self._frames / (now - self._last_log)
            det_rate = (self._faces_detected / max(1, self._frames)) * 100
            self.get_logger().info(
                f"frames={self._frames} "
                f"({rate:.1f} Hz, face_detected={det_rate:.0f}%)"
            )
            self._frames = 0
            self._faces_detected = 0
            self._last_log = now

    def destroy_node(self):
        if hasattr(self, 'cap') and self.cap is not None:
            self.cap.release()
        if hasattr(self, 'landmarker') and self.landmarker is not None:
            self.landmarker.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GevaNode()
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
