"""mode_guiding.launch.py — 동행 안내(guiding) 모드 stack (M2 실 구현).

mode_manager 가 SetMode("guiding", {"target_table":"T02","customer_id":"C-..."})
요청 시 spawn. RPi v4l2_camera_node (scripts/run_robot_cam.sh) 가 별도 가동되어
/robot_cam/image_raw 가 들어와야 함. /scan + Nav2 도 별도 가동 가정.

설계 SoT: docs/moca_guiding_design.md §3.

★ M1 → M2 교체: M1 에서는 임시로 follow stack (person_detector + follow_controller)
   재사용. M2 에서 진짜 guiding_controller_node 로 교체. follow_controller 와는
   알고리즘 정반대 (follow=주인 추적 reactive, guiding=로봇 앞장 supervised).
   디자인 §1: 코드 재사용 < 30%.

노드 구성:
  - person_detector (dobi_npc_emotion, 기존 — follow 가 사용하던 것 재사용):
      /image_raw 또는 /robot_cam/image_raw → /robot_cam/persons (Detection2DArray)
  - guiding_controller (mobility_controller, M2 신규):
      tables.yaml + params(target_table, customer_id) → Nav2 + customer 추적
      + UtterRequest(face_expression 동기) → /guiding/state (1Hz)

launch 인자:
  params_json: SetMode 가 전달한 JSON params
               (예: '{"target_table":"T02","customer_id":"C-2026-05-16-0017"}')
  persons_topic: guiding_controller 가 구독할 person 검출 토픽 (default /robot_cam/persons)
  image_topic: person_detector 가 구독할 카메라 토픽 (default /image_raw)
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    params_arg = DeclareLaunchArgument(
        'params_json', default_value='',
        description='SetMode JSON params (target_table + customer_id)')
    persons_topic_arg = DeclareLaunchArgument(
        'persons_topic', default_value='/robot_cam/persons',
        description='person_detector 출력 토픽 (guiding_controller 가 구독)')
    image_topic_arg = DeclareLaunchArgument(
        'image_topic', default_value='/image_raw',
        description='person_detector 가 구독할 카메라 RGB 토픽')

    tables_yaml = PathJoinSubstitution([
        FindPackageShare('mobility_controller'), 'config', 'tables.yaml'])

    return LaunchDescription([
        params_arg,
        persons_topic_arg,
        image_topic_arg,

        # 1) person_detector — Detection2DArray 발행. follow 와 동일 노드 재사용.
        Node(
            package='dobi_npc_emotion', executable='person_detector',
            name='person_detector', output='screen',
            parameters=[{
                'input_topic': LaunchConfiguration('image_topic'),
                # follow_controller 와 동일 설정 (검증된 게인)
                'score_threshold': 0.3,
                'detect_rate_hz': 15.0,
            }],
        ),

        # 2) guiding_controller — Nav2 + customer 추적 supervised
        Node(
            package='mobility_controller', executable='guiding_controller',
            name='guiding_controller', output='screen',
            parameters=[{
                'tables_yaml': tables_yaml,
                'params_json': ParameterValue(
                    LaunchConfiguration('params_json'), value_type=str),
                'persons_topic': LaunchConfiguration('persons_topic'),
                # 디자인 §2.1.1 기본값
                'lock_on_timeout_sec': 10.0,
                'lag_distance_max_m': 1.5,
                'lag_distance_min_m': 1.0,
                'customer_lost_timeout_sec': 8.0,
                'arrival_dwell_sec': 5.0,
                'utter_cooldown_sec': 5.0,
                'nav_overall_timeout_sec': 90.0,
                'nav_action_name': '/navigate_to_pose',
            }],
        ),
    ])
