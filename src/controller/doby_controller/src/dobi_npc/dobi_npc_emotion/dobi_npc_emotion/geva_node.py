#!/usr/bin/env python3
"""GEVA — Gesture/Expression Vision Analyzer (얼굴 표정 → V·A).

Phase 2 W4. EyeCon v3.5 vision.py + analyzer._classify_emotion 포팅.

2026-05-26 수정: 노트북 웹캠 → 로봇 카메라(/robot_cam/image_raw) 통일.
person_tracking tracks 의 각 bbox 안에서 표정 분석 후 track_id 포함 발행.
→ customer_identity_node 와 연동해 추종 대상 특정 가능.

파이프라인:
  1) /robot_cam/image_raw (또는 compressed) 구독 → 최신 프레임 보관
  2) /person_tracking/tracks 수신 시 각 track bbox ROI 추출
  3) MediaPipe FaceLandmarker (IMAGE 모드, output_face_blendshapes=True)
  4) Blendshapes 규칙 엔진으로 7감정 점수(softmax)
  5) Russell circumplex 좌표(Posner 2005 근사)로 가중평균 → (V, A)
  6) valence 가장 높은 track 의 /emotion/state (track_id 포함) 발행

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

from cv_bridge import CvBridge
from sensor_msgs.msg import Image, CompressedImage

from dobi_npc_msgs.msg import EmotionState, PersonTrackArray


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
    """GEVA 노드 — 로봇 카메라 + person_tracking tracks → 표정 → V·A → /emotion/state."""

    def __init__(self):
        super().__init__('geva_node')

        self.declare_parameter('camera_index', 0)
        self.declare_parameter('image_topic', '/robot_cam/image_raw')  # 비우면 camera_index 웹캠 직접; 설정 시 해당 Image 토픽 구독
        self.declare_parameter('use_compressed', True)
        self.declare_parameter('publish_rate_hz', 10.0)
        self.declare_parameter('model_path', '')  # 비우면 share/models/face_landmarker.task
        self.declare_parameter('min_detection_confidence', 0.5)
        self.declare_parameter('min_tracking_confidence', 0.5)

        self._camera_index = self.get_parameter('camera_index').value
        image_topic = self.get_parameter('image_topic').value
        use_compressed = bool(self.get_parameter('use_compressed').value)
        publish_rate_hz = float(self.get_parameter('publish_rate_hz').value)
        model_path = self.get_parameter('model_path').value or self._default_model_path()
        min_det = float(self.get_parameter('min_detection_confidence').value)
        min_trk = float(self.get_parameter('min_tracking_confidence').value)

        if not os.path.isfile(model_path):
            raise FileNotFoundError(
                f"FaceLandmarker 모델이 없음: {model_path}. "
                f"`scripts/download_models.sh` 실행 필요."
            )

        self._bridge = CvBridge()
        self._latest_bgr = None
        self.cap = None

        if image_topic:
            # ROS 토픽 구독 (로봇 카메라)
            if use_compressed:
                self.create_subscription(
                    CompressedImage, image_topic + '/compressed', self._on_compressed, 10)
            else:
                self.create_subscription(Image, image_topic, self._on_image, 10)
            self.get_logger().info(f"이미지 토픽 구독: {image_topic}")
        else:
            # 웹캠 직접 사용
            self.cap = cv2.VideoCapture(self._camera_index)
            if not self.cap.isOpened():
                raise RuntimeError(f"웹캠 열기 실패: index={self._camera_index}")
            self.create_timer(1.0 / publish_rate_hz, self._read_webcam)
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

        # person_tracking tracks 구독 → bbox별 감정 분석 트리거
        self.create_subscription(
            PersonTrackArray,
            '/person_tracking/tracks',
            self._on_tracks, 10)

        self.pub = self.create_publisher(EmotionState, '/emotion/state', 10)

        self._frames = 0
        self._faces_detected = 0
        self._last_log = time.time()

        self.get_logger().info(
            f"geva_node ready: image={image_topic} "
            f"compressed={use_compressed}"
        )

    @staticmethod
    def _default_model_path() -> str:
        share = get_package_share_directory('dobi_npc_emotion')
        return os.path.join(share, 'models', 'face_landmarker.task')

    # ── 이미지 콜백 ────────────────────────────────────────────

    def _on_compressed(self, msg: CompressedImage):
        arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            self._latest_bgr = frame

    def _on_image(self, msg):
        try:
            self._latest_bgr = self._bridge.imgmsg_to_cv2(msg, 'bgr8')
        except Exception as e:
            self.get_logger().warn(f'image 변환 실패: {e}')

    def _read_webcam(self):
        """웹캠 직접 사용 시 타이머로 프레임 읽기."""
        if self.cap:
            ok, frame = self.cap.read()
            if ok:
                self._latest_bgr = frame

    # ── tracks 콜백 → bbox별 감정 분석 ────────────────────────

    def _on_tracks(self, msg: PersonTrackArray):
        if self._latest_bgr is None:
            return
        if not msg.tracks:
            return

        h, w = self._latest_bgr.shape[:2]
        best_msg = None
        best_valence = -2.0
        self._frames += 1

        for track in msg.tracks:
            x1, y1, x2, y2 = (int(v) for v in track.bbox)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 <= x1 or y2 <= y1:
                continue

            roi = self._latest_bgr[y1:y2, x1:x2]
            rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            try:
                result = self.landmarker.detect(mp_image)
            except Exception as e:
                self.get_logger().warn(f'FaceLandmarker.detect 실패 (track {track.track_id}): {e}')
                continue

            if not result.face_landmarks or not result.face_blendshapes:
                continue  # 이 bbox 안에 얼굴 없음 → 다음 track

            self._faces_detected += 1
            bs = {cat.category_name: cat.score for cat in result.face_blendshapes[0]}
            scores = classify_emotion_from_blendshapes(bs)
            v, a, top = emotion_scores_to_va(scores)
            top_emotion = max(scores, key=scores.get)

            emotion_msg = EmotionState()
            emotion_msg.header.stamp = self.get_clock().now().to_msg()
            emotion_msg.header.frame_id = 'robot_cam_link'
            emotion_msg.source = 'face'
            emotion_msg.track_id = int(track.track_id)
            emotion_msg.valence = v
            emotion_msg.arousal = a
            emotion_msg.confidence = top
            emotion_msg.flags = [f'top:{top_emotion}']

            # valence 가장 높은 사람 선택 (가장 호감 있는 사람)
            if v > best_valence:
                best_valence = v
                best_msg = emotion_msg

        if best_msg is not None:
            self.pub.publish(best_msg)
            self.get_logger().debug(
                f'emotion: track_id={best_msg.track_id} '
                f'v={best_msg.valence:.2f} a={best_msg.arousal:.2f} '
                f'conf={best_msg.confidence:.2f} flags={best_msg.flags}'
            )

        self._maybe_log()

    def _maybe_log(self):
        now = time.time()
        if now - self._last_log >= 5.0:
            elapsed = now - self._last_log
            rate = self._frames / elapsed
            det_rate = (self._faces_detected / max(1, self._frames)) * 100
            self.get_logger().info(
                f"frames={self._frames} "
                f"({rate:.1f} Hz, face_detected={det_rate:.0f}%)"
            )
            self._frames = 0
            self._faces_detected = 0
            self._last_log = now

    def destroy_node(self):
        if hasattr(self, 'cap') and self.cap:
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
