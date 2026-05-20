# Person Tracking ↔ 모객 BT Funnel 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `person_tracking_pkg` (YOLO+Pose+BoT-SORT) 출력을 모객 BT funnel 의 IdleScan/Approach 로 흡수해서 노트북 단독 환경에서 funnel 한 사이클을 토픽 흐름 수준까지 검증한다.

**Architecture:** BT 는 `/approach/enable` Bool 게이트로 `approach_controller_node` 의 PD 제어를 ON/OFF. BT IdleScan 은 `/person_tracking/tracks` 구독 후 5 프레임 안정 시 SUCCESS. BT Approach 는 `/customer_pose.z (bh)` 안정 + lost timeout 으로 SUCCESS/FAILURE. 카메라는 `webcam_master` (v4l2_camera_node) 1단 마스터 → geva + person_tracking 양쪽 구독.

**Tech Stack:** ROS2 Jazzy / BehaviorTree.CPP 4.8.3 / Python rclpy / C++ rclcpp / v4l2_camera / 팀원 머지 person_tracking_pkg (YOLOv8n + BoT-SORT + MediaPipe Pose)

**Spec:** `docs/superpowers/specs/2026-05-20-person-tracking-bt-integration-design.md`

**§0-B 영향:** 0 — `src/shared/vic_pinky/` + RPi `~/vicpinky_ws/` + `scripts/run_vic_bringup.sh` 등 보호 자산 touch 0.

---

## Task 1: 일일 백업 (plan 시작 전)

**Files:** Create `~/backup/moca_daily_20260520/`

CLAUDE.md §7 일일 백업 루틴. RPi 접근 금지 (§0-A) 신호 시 PC 백업만.

- [ ] **Step 1: PC src/scripts/config/launch/docs 백업 + git state 캡처**

```bash
mkdir -p ~/backup/moca_daily_20260520/laptop
cd ~/moca
git status > ~/backup/moca_daily_20260520/laptop/git_state.txt
git log --oneline -20 >> ~/backup/moca_daily_20260520/laptop/git_state.txt
git diff > ~/backup/moca_daily_20260520/laptop/moca_unstaged.patch
git diff --cached > ~/backup/moca_daily_20260520/laptop/moca_staged.patch
tar czf ~/backup/moca_daily_20260520/laptop/moca_src_$(git rev-parse --short HEAD).tar.gz \
    --exclude='build' --exclude='install' --exclude='log' \
    --exclude='maps' --exclude='datasets' --exclude='.venv' \
    --exclude='__pycache__' --exclude='*.pyc' \
    src/ scripts/ config/ docs/ CLAUDE.md README.md moca.repos .gitignore
```

- [ ] **Step 2: README 작성**

```bash
cat > ~/backup/moca_daily_20260520/README.md <<EOF
# 2026-05-20 일일 백업

- 사유: person_tracking ↔ BT funnel 통합 trake 시작 전 백업
- git sha: $(cd ~/moca && git rev-parse --short HEAD)
- RPi: §0-A 신호로 SSH 접근 X (PC 백업만)
- network: \$(hostname -I)
EOF
```

- [ ] **Step 3: 백업 SHA256 검증**

```bash
cd ~/backup/moca_daily_20260520
find . -type f -name "*.tar.gz" -exec sha256sum {} \; > SHA256SUMS
sha256sum -c SHA256SUMS
```

Expected: 모든 tar.gz 가 `OK`

---

## Task 2: BT IdleScan 노드 전면 개편 (Stateful + tracks 구독)

**Files:**
- Modify: `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/idle_scan.hpp`
- Modify: `src/dobi_npc/dobi_npc_bt/src/bt_executor_node.cpp:60` (IdleScan 등록 시 node 인자 추가)
- Modify: `src/dobi_npc/dobi_npc_bt/CMakeLists.txt` (dobi_npc_msgs 의존성 확인)

- [ ] **Step 1: idle_scan.hpp 전면 재작성**

```cpp
// idle_scan.hpp
// Phase 2 W4 후속: person_tracking_pkg 통합. /person_tracking/tracks 구독 후
// tracks.size>=1 이 stable_frames 연속 안정 시 SUCCESS + top track_id 출력.
//
// === 동작 흐름 ===
//   onStart:  stable_count_ = 0, RUNNING
//   onRunning: tracks.size>=1 → stable_count++ 아니면 reset
//              stable_count>=stable_frames → SUCCESS + customer_id 출력
//              아니면 RUNNING
//   onHalted: no-op

#ifndef DOBI_NPC_BT__IDLE_SCAN_HPP_
#define DOBI_NPC_BT__IDLE_SCAN_HPP_

#include <algorithm>
#include <memory>
#include <string>

#include "behaviortree_cpp/action_node.h"
#include "rclcpp/rclcpp.hpp"
#include "dobi_npc_msgs/msg/person_track_array.hpp"

namespace dobi_npc_bt
{

class IdleScan : public BT::StatefulActionNode
{
public:
  IdleScan(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : BT::StatefulActionNode(name, config),
    node_(std::move(ros_node))
  {
    tracks_sub_ = node_->create_subscription<dobi_npc_msgs::msg::PersonTrackArray>(
      "/person_tracking/tracks", 10,
      [this](const dobi_npc_msgs::msg::PersonTrackArray::SharedPtr msg) {
        last_tracks_ = *msg;
      });
  }

  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<int>(
        "stable_frames", 5, "사람 발견 연속 안정 프레임 (default 5)"),
      BT::OutputPort<std::string>(
        "customer_id", "탐지된 고객 track_id (가장 큰 bbox 사람)"),
    };
  }

  BT::NodeStatus onStart() override
  {
    stable_count_ = 0;
    return BT::NodeStatus::RUNNING;
  }

  BT::NodeStatus onRunning() override
  {
    int stable_frames = 5;
    getInput("stable_frames", stable_frames);

    if (!last_tracks_.tracks.empty()) {
      stable_count_++;
      if (stable_count_ >= stable_frames) {
        const auto & top = *std::max_element(
          last_tracks_.tracks.begin(), last_tracks_.tracks.end(),
          [](const auto & a, const auto & b) {
            const float a_area = (a.bbox[2] - a.bbox[0]) * (a.bbox[3] - a.bbox[1]);
            const float b_area = (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1]);
            return a_area < b_area;
          });
        setOutput("customer_id", std::to_string(top.track_id));
        RCLCPP_INFO(node_->get_logger(),
          "[IdleScan] SUCCESS — customer_id=%d stable=%d tracks=%zu",
          top.track_id, stable_count_, last_tracks_.tracks.size());
        return BT::NodeStatus::SUCCESS;
      }
    } else {
      stable_count_ = 0;
    }
    return BT::NodeStatus::RUNNING;
  }

  void onHalted() override
  {
    // no-op
  }

private:
  rclcpp::Node::SharedPtr node_;
  rclcpp::Subscription<dobi_npc_msgs::msg::PersonTrackArray>::SharedPtr tracks_sub_;
  dobi_npc_msgs::msg::PersonTrackArray last_tracks_;
  int stable_count_ = 0;
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__IDLE_SCAN_HPP_
```

- [ ] **Step 2: bt_executor_node.cpp 의 IdleScan 등록에 node 인자 추가**

`src/dobi_npc/dobi_npc_bt/src/bt_executor_node.cpp` 의 line 60 변경:

```cpp
// 변경 전:
//   factory.registerNodeType<dobi_npc_bt::IdleScan>("IdleScan");
// 변경 후:
  factory.registerNodeType<dobi_npc_bt::IdleScan>("IdleScan", node);
```

- [ ] **Step 3: CMakeLists.txt 에 dobi_npc_msgs find_package 확인**

```bash
grep "find_package(dobi_npc_msgs" src/dobi_npc/dobi_npc_bt/CMakeLists.txt
```

Expected: 라인이 이미 존재 (이전 Approach 가 사용 중). 없으면 추가:

```cmake
find_package(dobi_npc_msgs REQUIRED)
# 그리고 ament_target_dependencies(bt_executor ... dobi_npc_msgs)
```

- [ ] **Step 4: 빌드 검증**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --packages-select dobi_npc_bt --symlink-install
'
```

Expected: `Summary: 1 package finished` 통과

- [ ] **Step 5: 커밋**

```bash
cd ~/moca
git add src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/idle_scan.hpp \
        src/dobi_npc/dobi_npc_bt/src/bt_executor_node.cpp
git commit -m "BT IdleScan: Stateful + /person_tracking/tracks 5-frame stable 판정"
```

---

## Task 3: BT Approach 노드 전면 개편 (Nav2 제거 + enable 발행 + bh 안정)

**Files:**
- Modify: `src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/approach.hpp` (전면 재작성)

- [ ] **Step 1: approach.hpp 전면 재작성**

```cpp
// approach.hpp
// Phase 2 W4 후속: Nav2 액션 코드 제거. approach_controller_node 의 PD 제어를
// /approach/enable Bool 게이트로 ON/OFF. bbox 높이 비율 (bh) 안정 검사로 SUCCESS.
//
// === 동작 흐름 ===
//   onStart:   stable_count_=0, last_track_seen_=now, /approach/enable=true 발행, RUNNING
//   onRunning: now - last_track_seen_ > lost_timeout_sec → enable=false + FAILURE
//              bh >= bh_threshold → stable_count++
//              stable_count >= stable_frames → enable=false + SUCCESS
//   onHalted:  enable=false 발행

#ifndef DOBI_NPC_BT__APPROACH_HPP_
#define DOBI_NPC_BT__APPROACH_HPP_

#include <memory>
#include <string>
#include <utility>

#include "behaviortree_cpp/action_node.h"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/bool.hpp"
#include "geometry_msgs/msg/pose_stamped.hpp"
#include "dobi_npc_msgs/msg/person_track_array.hpp"

namespace dobi_npc_bt
{

class Approach : public BT::StatefulActionNode
{
public:
  Approach(
    const std::string & name,
    const BT::NodeConfig & config,
    rclcpp::Node::SharedPtr ros_node)
  : BT::StatefulActionNode(name, config),
    node_(std::move(ros_node))
  {
    enable_pub_ = node_->create_publisher<std_msgs::msg::Bool>(
      "/approach/enable", 10);

    pose_sub_ = node_->create_subscription<geometry_msgs::msg::PoseStamped>(
      "/customer_pose", 10,
      [this](const geometry_msgs::msg::PoseStamped::SharedPtr msg) {
        last_bh_ = msg->pose.position.z;
        has_pose_ = true;
      });

    tracks_sub_ = node_->create_subscription<dobi_npc_msgs::msg::PersonTrackArray>(
      "/person_tracking/tracks", 10,
      [this](const dobi_npc_msgs::msg::PersonTrackArray::SharedPtr msg) {
        if (!msg->tracks.empty()) {
          last_track_seen_ = node_->now();
        }
      });

    last_track_seen_ = node_->now();
  }

  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<std::string>(
        "customer_id", "", "(미사용 — IdleScan 출력 호환)"),
      BT::InputPort<double>(
        "bh_threshold", 0.6, "bbox 높이 비율 종료 임계 (0~1, 클수록 가까움)"),
      BT::InputPort<int>(
        "stable_frames", 5, "bh 안정 프레임 (default 5)"),
      BT::InputPort<double>(
        "lost_timeout_sec", 2.0, "사람 lost 허용 시간 (초)"),
    };
  }

  BT::NodeStatus onStart() override
  {
    stable_count_ = 0;
    last_track_seen_ = node_->now();
    publish_enable(true);
    RCLCPP_INFO(node_->get_logger(), "[Approach] start — /approach/enable=true");
    return BT::NodeStatus::RUNNING;
  }

  BT::NodeStatus onRunning() override
  {
    double bh_threshold = 0.6;
    int stable_frames = 5;
    double lost_timeout_sec = 2.0;
    getInput("bh_threshold", bh_threshold);
    getInput("stable_frames", stable_frames);
    getInput("lost_timeout_sec", lost_timeout_sec);

    const auto now = node_->now();
    if ((now - last_track_seen_).seconds() > lost_timeout_sec) {
      RCLCPP_WARN(node_->get_logger(),
        "[Approach] lost timeout (%.1fs) — FAILURE", lost_timeout_sec);
      publish_enable(false);
      return BT::NodeStatus::FAILURE;
    }

    if (has_pose_ && last_bh_ >= bh_threshold) {
      stable_count_++;
      if (stable_count_ >= stable_frames) {
        RCLCPP_INFO(node_->get_logger(),
          "[Approach] SUCCESS — bh=%.2f stable=%d", last_bh_, stable_count_);
        publish_enable(false);
        return BT::NodeStatus::SUCCESS;
      }
    } else {
      stable_count_ = 0;
    }
    return BT::NodeStatus::RUNNING;
  }

  void onHalted() override
  {
    publish_enable(false);
    RCLCPP_INFO(node_->get_logger(), "[Approach] halted — /approach/enable=false");
  }

private:
  void publish_enable(bool v)
  {
    std_msgs::msg::Bool msg;
    msg.data = v;
    enable_pub_->publish(msg);
  }

  rclcpp::Node::SharedPtr node_;
  rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr enable_pub_;
  rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr pose_sub_;
  rclcpp::Subscription<dobi_npc_msgs::msg::PersonTrackArray>::SharedPtr tracks_sub_;

  double last_bh_ = 0.0;
  bool has_pose_ = false;
  rclcpp::Time last_track_seen_;
  int stable_count_ = 0;
};

}  // namespace dobi_npc_bt

#endif  // DOBI_NPC_BT__APPROACH_HPP_
```

- [ ] **Step 2: 빌드 검증**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --packages-select dobi_npc_bt --symlink-install
'
```

Expected: 통과. 만약 `nav2_msgs` 또는 `rclcpp_action` 의존성 unused 경고 시 무시 (다른 BT 노드가 여전히 사용 중).

- [ ] **Step 3: 커밋**

```bash
git add src/dobi_npc/dobi_npc_bt/include/dobi_npc_bt/approach.hpp
git commit -m "BT Approach: Nav2 액션 제거 + /approach/enable 게이트 + bh 안정 검사"
```

---

## Task 4: approach_controller_node `/approach/enable` 게이트 추가

**Files:**
- Modify: `src/dobi_npc/person_tracking_pkg/person_tracking_pkg/approach_controller_node.py`
- Create: `src/dobi_npc/person_tracking_pkg/test/test_approach_controller_gate.py`

- [ ] **Step 1: pytest 테스트 작성 (실패할 테스트)**

```python
# src/dobi_npc/person_tracking_pkg/test/test_approach_controller_gate.py
"""approach_controller_node /approach/enable 게이트 단위 테스트."""
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import Bool
from geometry_msgs.msg import Twist, PoseStamped
from std_msgs.msg import Int32

from person_tracking_pkg.approach_controller_node import ApproachControllerNode


@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


def test_disable_default_no_publish(ros_context):
    """기본 상태(enable=False)에서 cmd_vel 발행 안 함."""
    node = ApproachControllerNode()

    received = []
    sub_node = rclpy.create_node('test_sub')
    sub_node.create_subscription(
        Twist, '/bt/cmd_vel', lambda m: received.append(m), 10)

    # target + pose 모두 설정 (정상이면 cmd_vel 발행 조건 충족)
    pub_target = sub_node.create_publisher(Int32, '/person_tracking/approach_target', 10)
    pub_pose = sub_node.create_publisher(PoseStamped, '/customer_pose', 10)

    target_msg = Int32(); target_msg.data = 0; pub_target.publish(target_msg)
    pose_msg = PoseStamped()
    pose_msg.pose.position.x = 0.3
    pose_msg.pose.position.y = 0.5
    pose_msg.pose.position.z = 0.4
    pub_pose.publish(pose_msg)

    exec_ = SingleThreadedExecutor()
    exec_.add_node(node)
    exec_.add_node(sub_node)

    # 2초간 spin (controller cmd_rate=10Hz → 20 tick)
    import time
    start = time.time()
    while time.time() - start < 2.0:
        exec_.spin_once(timeout_sec=0.1)

    node.destroy_node()
    sub_node.destroy_node()

    assert len(received) == 0, f"enable=False 이지만 {len(received)} 회 cmd_vel 발행됨"


def test_enable_true_then_publish(ros_context):
    """enable=True 토글 후 cmd_vel 발행."""
    node = ApproachControllerNode()

    received = []
    sub_node = rclpy.create_node('test_sub2')
    sub_node.create_subscription(
        Twist, '/bt/cmd_vel', lambda m: received.append(m), 10)
    pub_target = sub_node.create_publisher(Int32, '/person_tracking/approach_target', 10)
    pub_pose = sub_node.create_publisher(PoseStamped, '/customer_pose', 10)
    pub_enable = sub_node.create_publisher(Bool, '/approach/enable', 10)

    target_msg = Int32(); target_msg.data = 0; pub_target.publish(target_msg)
    pose_msg = PoseStamped()
    pose_msg.pose.position.x = 0.3
    pose_msg.pose.position.y = 0.5
    pose_msg.pose.position.z = 0.4
    pub_pose.publish(pose_msg)
    enable_msg = Bool(); enable_msg.data = True; pub_enable.publish(enable_msg)

    exec_ = SingleThreadedExecutor()
    exec_.add_node(node)
    exec_.add_node(sub_node)

    import time
    start = time.time()
    while time.time() - start < 2.0:
        exec_.spin_once(timeout_sec=0.1)

    node.destroy_node()
    sub_node.destroy_node()

    assert len(received) > 0, "enable=True 이지만 cmd_vel 미발행"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
cd src/dobi_npc/person_tracking_pkg
python3 -m pytest test/test_approach_controller_gate.py -v
'
```

Expected: `test_disable_default_no_publish` FAIL (현재 controller 는 게이트 없어 발행 함). `test_enable_true_then_publish` 도 무관히 PASS.

- [ ] **Step 3: approach_controller_node.py patch — 게이트 추가**

기존 파일에 변경:

`approach_controller_node.py:20` 의 import 에 추가:

```python
from std_msgs.msg import Bool, Int32
```

`__init__` 메서드 내 (subscription 추가 위치, line 60 근처) 신규 구독 + 상태 추가:

```python
# /approach/enable 게이트 — default False (BT 가 명시적 True 발행 시에만 cmd_vel 출력)
self._enable: bool = False
self._sub_enable = self.create_subscription(
    Bool, '/approach/enable', self._cb_enable, 10)
```

새 callback 메서드 (클래스 내 다른 callback 근처):

```python
def _cb_enable(self, msg: Bool) -> None:
    if self._enable and not msg.data:
        # disable 전환 — PD 상태 reset (재진입 race 방지)
        self._prev_err_x = 0.0
        self._d_filtered = 0.0
        self.get_logger().info('[approach_controller] /approach/enable=False (PD reset)')
    elif not self._enable and msg.data:
        self.get_logger().info('[approach_controller] /approach/enable=True')
    self._enable = msg.data
```

`_tick` 메서드 진입부 (line 80 근처) 게이트 추가:

```python
def _tick(self) -> None:
    if not self._enable:
        return  # publish skip → twist_mux pose_timeout 후 하위 채널이 권한 확보
    # 기존 로직 그대로 ...
```

- [ ] **Step 4: 빌드 + 테스트 통과 확인**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --packages-select person_tracking_pkg --symlink-install
source install/setup.bash
cd src/dobi_npc/person_tracking_pkg
python3 -m pytest test/test_approach_controller_gate.py -v
'
```

Expected: `test_disable_default_no_publish PASSED`, `test_enable_true_then_publish PASSED`

- [ ] **Step 5: 커밋**

```bash
git add src/dobi_npc/person_tracking_pkg/person_tracking_pkg/approach_controller_node.py \
        src/dobi_npc/person_tracking_pkg/test/test_approach_controller_gate.py
git commit -m "approach_controller: /approach/enable Bool 게이트 + PD reset on disable"
```

---

## Task 5: geva_node 토픽 구독 전환 (cv2.VideoCapture 제거)

**Files:**
- Modify: `src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py`

- [ ] **Step 1: import 추가 + cv2.VideoCapture 제거**

`geva_node.py` 의 변경 4 곳:

**(a) import 추가 (line 27 근처)**:

```python
import threading
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
```

**(b) `__init__` 의 카메라 직접 open 제거 + 토픽 구독 추가**:

기존 line 137-166 의 `self.declare_parameter('camera_index', 0)` ~ `self.cap = cv2.VideoCapture(...)` ~ `self.get_logger().info("웹캠 열림...")` 를 다음으로 교체:

```python
self.declare_parameter('input_topic', '/webcam/image_raw')
self.declare_parameter('publish_rate_hz', 10.0)
self.declare_parameter('model_path', '')
self.declare_parameter('min_detection_confidence', 0.5)
self.declare_parameter('min_tracking_confidence', 0.5)

input_topic = self.get_parameter('input_topic').value
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
self._last_frame = None
self._frame_lock = threading.Lock()
self._sub = self.create_subscription(Image, input_topic, self._cb_image, 10)
self.get_logger().info(f"입력 토픽 구독: {input_topic}")
```

**(c) 신규 `_cb_image` callback 추가 (`_tick` 메서드 직전)**:

```python
def _cb_image(self, msg: Image) -> None:
    try:
        frame = self._bridge.imgmsg_to_cv2(msg, 'bgr8')
    except Exception as e:
        self.get_logger().warning(f"cv_bridge 변환 실패: {e}")
        return
    with self._frame_lock:
        self._last_frame = frame
```

**(d) `_tick` 메서드 (line 194~) 의 `ok, frame = self.cap.read()` 부분을 토픽 구독 프레임 사용으로 교체**:

```python
def _tick(self):
    with self._frame_lock:
        frame = self._last_frame
    if frame is None:
        return  # 아직 첫 프레임 미수신
    self._frames += 1

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    # ... 기존 로직 그대로 (try detect 등) ...
```

**(e) `destroy_node` 의 `self.cap.release()` 제거**:

```python
def destroy_node(self):
    if hasattr(self, 'landmarker') and self.landmarker is not None:
        self.landmarker.close()
    super().destroy_node()
```

- [ ] **Step 2: 빌드 검증**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --packages-select dobi_npc_emotion --symlink-install
'
```

Expected: 통과.

- [ ] **Step 3: import smoke (실행 X, import 만)**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
python3 -c "from dobi_npc_emotion.geva_node import GevaNode; print(\"OK\")"
'
```

Expected: `OK` 출력.

- [ ] **Step 4: 커밋**

```bash
git add src/dobi_npc/dobi_npc_emotion/dobi_npc_emotion/geva_node.py
git commit -m "geva_node: cv2.VideoCapture 폐기 → /webcam/image_raw 토픽 구독"
```

---

## Task 6: dev_common.launch.py — webcam_master + use_webcam arg

**Files:**
- Modify: `src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py`

- [ ] **Step 1: dev_common.launch.py 신규 import + arg 추가**

`dev_common.launch.py` 의 변경:

**(a) line 36-39 import 추가**:

```python
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch.conditions import IfCondition
from launch_ros.actions import Node
```

**(b) `generate_launch_description()` 내 launch arg 3 개 추가 (기존 fullscreen/persona/initial_mode 옆)**:

```python
use_webcam_arg = DeclareLaunchArgument(
    'use_webcam', default_value='true',
    description='노트북 카메라 1단 마스터 (webcam_master) 활성 + '
                'person_tracking 입력을 /webcam/image_raw 로 전환. '
                'false 시 webcam_master skip + person_tracking 은 /robot_cam/image_raw 구독 '
                '(RPi 라이브 모드).')
webcam_device_arg = DeclareLaunchArgument(
    'webcam_device', default_value='/dev/video0',
    description='webcam_master 가 열 v4l2 device 경로')
```

**(c) `LaunchDescription([...])` 리스트에 `use_webcam_arg`, `webcam_device_arg` 추가**:

```python
return LaunchDescription([
    fullscreen_arg,
    persona_arg,
    initial_mode_arg,
    use_webcam_arg,
    webcam_device_arg,
    # ... 기존 노드들 ...
])
```

**(d) `webcam_master` Node 추가 (geva_node 노드 직전)**:

```python
Node(
    package='v4l2_camera', executable='v4l2_camera_node',
    name='webcam_master', output='screen',
    parameters=[{
        'image_size': [640, 480],
        'camera_frame_id': 'webcam_link',
        'video_device': LaunchConfiguration('webcam_device'),
        'pixel_format': 'YUYV',
    }],
    remappings=[('image_raw', '/webcam/image_raw')],
    condition=IfCondition(LaunchConfiguration('use_webcam')),
),
```

**(e) `geva_node` Node 의 parameters 에 `input_topic` 추가 (기존 parameters 없으면 신규 추가)**:

```python
Node(
    package='dobi_npc_emotion', executable='geva_node',
    name='geva_node', output='screen',
    parameters=[{'input_topic': '/webcam/image_raw'}],
),
```

**(f) `person_tracking_node` Node 의 parameters 의 `input_topic` 분기 (line 96~101 의 hardcoded `/robot_cam/image_raw` 교체)**:

```python
Node(
    package='person_tracking_pkg', executable='person_tracking_node',
    name='person_tracking_node', output='screen',
    parameters=[{
        'input_topic': PythonExpression([
            "'/webcam/image_raw' if '",
            LaunchConfiguration('use_webcam'),
            "' == 'true' else '/robot_cam/image_raw'"
        ]),
        'use_compressed': False,  # webcam_master 는 compressed 안 만들기 → 변경
        'publish_visualization': True,
        'dbscan_eps': 50.0,
    }],
),
```

**주의**: `use_compressed=True` 였으나 v4l2_camera_node 가 compressed 자동 발행 X. False 로 변경. (또는 image_transport republish 노드 추가도 가능하지만 본 plan 에선 raw 만 사용.)

- [ ] **Step 2: 빌드 검증**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --packages-select dobi_npc_bringup --symlink-install
'
```

Expected: 통과 (Python launch 파일이라 빌드는 install symlink 만 갱신).

- [ ] **Step 3: launch description parse smoke**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch dobi_npc_bringup dev_common.launch.py --show-args
'
```

Expected: 5 개 args 표시 (fullscreen, default_persona, initial_mode, use_webcam, webcam_device). 에러 X.

- [ ] **Step 4: 커밋**

```bash
git add src/dobi_npc/dobi_npc_bringup/launch/dev_common.launch.py
git commit -m "dev_common: webcam_master 추가 + use_webcam arg + person_tracking input 분기"
```

---

## Task 7: cafe_funnel_v1.xml 포트 갱신

**Files:**
- Modify: `src/dobi_npc/dobi_npc_bt/bt_xml/cafe_funnel_v1.xml`

- [ ] **Step 1: IdleScan + Approach 노드 포트 교체**

`cafe_funnel_v1.xml` 의 변경 (line 48-50, 53-56 부근):

```xml
<!-- Stage 1: 고객 후보 탐지 — person_tracking_node /person_tracking/tracks 안정 5 frames -->
<IdleScan name="stage1_idle_scan"
          stable_frames="5"
          customer_id="{customer_id}"/>

<!-- Stage 2: bh 안정 SUCCESS / lost 시 FAILURE / /approach/enable 토글 -->
<!-- Phase 2 W4 후속 (2026-05-20): Nav2 액션 폐기 → approach_controller PD 게이트 -->
<Approach name="stage2_approach"
          customer_id="{customer_id}"
          bh_threshold="0.6"
          stable_frames="5"
          lost_timeout_sec="2.0"/>
```

- [ ] **Step 2: 빌드 검증**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --packages-select dobi_npc_bt --symlink-install
'
```

Expected: 통과 (XML 은 install/share/dobi_npc_bt/bt_xml/ 에 symlink 됨).

- [ ] **Step 3: BT XML 로드 smoke (bt_executor 1초 실행 후 종료)**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
timeout 3 ros2 run dobi_npc_bt bt_executor 2>&1 | head -30
'
```

Expected:
- `Registered: N user + M builtin nodes` 출력
- `Using default BT XML: ...cafe_funnel_v1.xml`
- `Starting BT tick loop @ 100 ms`
- `Failed to create tree` 에러 X

- [ ] **Step 4: 커밋**

```bash
git add src/dobi_npc/dobi_npc_bt/bt_xml/cafe_funnel_v1.xml
git commit -m "cafe_funnel_v1.xml: IdleScan stable_frames + Approach bh_threshold/stable/lost_timeout 포트"
```

---

## Task 8: 통합 빌드 + 전체 패키지 검증

**Files:** (없음 — 검증만)

- [ ] **Step 1: 전체 패키지 격리 셸 빌드**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
'
```

Expected: `Summary: 12 packages finished` (또는 워크스페이스에 추가 패키지 있으면 그 이상). 0 errors.

- [ ] **Step 2: ros2 pkg list 검증**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 pkg list | grep -E "dobi_npc|person_tracking|vicpinky" | sort
'
```

Expected:
```
dobi_npc_bringup
dobi_npc_bt
dobi_npc_dialog
dobi_npc_emotion
dobi_npc_minigame
dobi_npc_msgs
person_tracking_pkg
vicpinky_description
vicpinky_navigation
```

- [ ] **Step 3: bt_executor 노드 등록 smoke (Approach + IdleScan ros_node 주입 확인)**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
timeout 5 ros2 run dobi_npc_bt bt_executor 2>&1 | grep -E "Registered|tree|tick"
'
```

Expected:
- `Registered: 9 user + ... builtin nodes` (DummyAction + SafetyCheck + IdleScan + Approach + IceBreak + Minigame + Offer + LeadIn + EmotionMonitor = 9)
- `Starting BT tick loop` 출력
- 에러 X

---

## Task 9: Phase A 검증 — 카메라 + 인식 흐름 (노트북 단독)

**Files:** (없음 — 라이브 검증)

- [ ] **Step 1: dev_common 노트북 단독 모드 띄우기**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true
' &
DEV_PID=$!
sleep 15  # YOLO 모델 로드 + 토픽 안정 대기
```

Expected: 노트북 카메라 LED 점등 (v4l2_camera_node 카메라 점유). 로그에 다음 출력:
- `webcam_master` 시작
- `geva_node` 입력 토픽 구독: /webcam/image_raw
- `YOLOv8 로딩` + `BoT-SORT 초기화` + `MediaPipe Pose 로딩`
- `person_tracking_node 준비 완료`

- [ ] **Step 2: 토픽 hz 검증 (5 토픽)**

별 터미널:

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
echo "=== /webcam/image_raw ==="
timeout 5 ros2 topic hz /webcam/image_raw
echo "=== /person_tracking/tracks ==="
timeout 5 ros2 topic hz /person_tracking/tracks
echo "=== /geva/state 또는 /emotion/state ==="
timeout 5 ros2 topic hz /emotion/state
'
```

Expected:
- `/webcam/image_raw`: ~30Hz (YUYV 640x480)
- `/person_tracking/tracks`: 10-30Hz
- `/emotion/state`: ~10Hz (geva_node publish_rate_hz default)

- [ ] **Step 3: 사람 검출 echo (카메라 앞에 서기)**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
echo "카메라 앞 1m 거리에 서서 5초 후 echo 시작..."
sleep 5
ros2 topic echo /customer_pose --once
ros2 topic echo /person_tracking/approach_target --once
ros2 topic echo /person_tracking/tracks --once
'
```

Expected:
- `/customer_pose`: x≈0.5 (중앙), y≈0.5, z≈0.3-0.5 (1m 거리 bbox 비율)
- `/person_tracking/approach_target`: data=0 이상 (group_id, min_group_size=1 적용)
- `/person_tracking/tracks`: tracks 배열 1+ 원소

- [ ] **Step 4: dev_common 종료**

```bash
kill $DEV_PID 2>/dev/null
pkill -f "v4l2_camera_node" 2>/dev/null
pkill -f "person_tracking" 2>/dev/null
pkill -f "geva_node" 2>/dev/null
sleep 2
```

- [ ] **Step 5: Phase A 합격 기준 체크**

| # | 항목 | 결과 |
|---|---|---|
| A1 | `/webcam/image_raw` 30Hz | □ |
| A2 | `/person_tracking/tracks` 10Hz 이상 | □ |
| A3 | `/customer_pose` 발행 (사람 있을 때) | □ |
| A4 | `/person_tracking/approach_target ≥ 0` (solo 손님) | □ |
| A5 | `/emotion/state` 발행 유지 (geva 토픽 구독 전환 검증) | □ |

5/5 모두 OK 면 Task 10 진행. 하나라도 실패 → 디버그 후 재시도.

---

## Task 10: Phase B 검증 — BT funnel 통합 1 사이클

**Files:** (없음 — 라이브 검증)

- [ ] **Step 1: dev_common + mode_engaging 띄우기**

```bash
cd ~/moca
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
ros2 launch dobi_npc_bringup dev_common.launch.py use_webcam:=true initial_mode:=engaging
' &
DEV_PID=$!
sleep 20  # dev_common 부팅 + mode_manager 가 engaging stack spawn 대기
```

Expected:
- dev_common 10 노드 + webcam_master 모두 spawn
- mode_manager 가 mode_engaging.launch.py 호출 → bt_executor + minigame_runner spawn
- bt_executor 로그: `Registered: 9 user + ... builtin nodes` + `Starting BT tick loop`

- [ ] **Step 2: /approach/enable 토글 시퀀스 검증**

별 터미널:

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1

# /approach/enable 변화 추적 (사람 카메라 앞 → 가까이 시퀀스)
ros2 topic echo /approach/enable --field data &
ECHO1=$!
ros2 topic echo /bt/cmd_vel --filter "abs(m.linear.x) > 0.01 or abs(m.angular.z) > 0.01" --field linear &
ECHO2=$!

echo "=== 시나리오 ==="
echo "1) 카메라에서 멀어진 채로 5초 대기 (IdleScan RUNNING)"
sleep 5
echo "2) 카메라 앞 1.5m 거리에 서기 — 1초 후 IdleScan SUCCESS → /approach/enable=true 발행"
sleep 5
echo "3) 카메라 앞 0.5m 거리로 가까이 — bh 0.6 이상 stable → Approach SUCCESS → /approach/enable=false"
sleep 8

kill $ECHO1 $ECHO2 2>/dev/null
'
```

Expected:
- 시점 1: `/approach/enable` 토픽 echo 없음 (BT IdleScan stage 에서 enable 발행 X)
- 시점 2: `[IdleScan] SUCCESS — customer_id=X stable=5` log + `data: true` echo + `/bt/cmd_vel` 발행 시작 (angular.z + linear.x)
- 시점 3: `[Approach] SUCCESS — bh=0.XX stable=5` log + `data: false` echo + `/bt/cmd_vel` 0 으로 복귀

- [ ] **Step 3: 후속 stage 진입 검증 (IceBreak)**

```bash
bash --noprofile --norc -c '
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_LOCALHOST_ONLY=1
timeout 10 ros2 topic echo /dialog/request
'
```

Expected (Phase B Step 2 시점 3 이후):
- `data: "casual_browser"` 또는 비슷한 phrase_pool_id 발행 (IceBreak stage 진입)

후속 stage (Minigame/Offer/LeadIn) 도 자동 진입. TTS 음성 + face_avatar 표정 변화도 함께 확인.

- [ ] **Step 4: 시스템 종료**

```bash
kill $DEV_PID 2>/dev/null
pkill -f "v4l2_camera_node" 2>/dev/null
pkill -f "person_tracking" 2>/dev/null
pkill -f "bt_executor" 2>/dev/null
pkill -f "geva_node" 2>/dev/null
pkill -f "minigame_runner" 2>/dev/null
sleep 2
```

- [ ] **Step 5: Phase B 합격 기준 체크**

| # | 항목 | 결과 |
|---|---|---|
| B1 | BT IdleScan 가 5 frames 안정 후 SUCCESS (단발 frame false-positive 없음) | □ |
| B2 | BT Approach onStart → `/approach/enable=true` 발행 | □ |
| B3 | `/approach/enable=true` 동안 `/bt/cmd_vel` 비-zero 발행 | □ |
| B4 | bh≥0.6 가 5 frames 안정 후 Approach SUCCESS → `/approach/enable=false` | □ |
| B5 | `/approach/enable=false` 후 `/bt/cmd_vel` 0 으로 복귀 | □ |
| B6 | IceBreak 진입 (`/dialog/request` 발행) | □ |
| B7 | (가용 시) Minigame / Offer / LeadIn 진입 | □ |

7/7 모두 OK 면 Task 11 진행. B6 까지만 통과해도 본 plan 의 핵심 통합은 검증 완료 — B7 은 기존 기능.

**모터 검증 (RPi 라이브)**: 본 plan 범위 밖. §0-A 해제 후 별 트랙.

---

## Task 11: 회고 .md 작성

**Files:**
- Create: `docs/daily/2026-05-20_person_tracking_bt_integration.md`

- [ ] **Step 1: 회고 파일 작성**

```bash
cat > docs/daily/2026-05-20_person_tracking_bt_integration.md <<'EOF'
# 2026-05-20 — person_tracking ↔ 모객 BT funnel 통합 (Phase 2 W4 후속)

> spec: `docs/superpowers/specs/2026-05-20-person-tracking-bt-integration-design.md`
> plan: `docs/superpowers/plans/2026-05-20-person-tracking-bt-integration-plan.md`
> 작성: 2026-05-20 (doby)

## 1. 무엇을 했는가

팀원 머지 (`f8fce31`) 로 들어온 `person_tracking_pkg` (YOLOv8 + DBSCAN + BoT-SORT +
MediaPipe Pose) 출력을 모객 BT funnel 의 IdleScan / Approach 로 흡수.

### 변경 7 파일

- `dobi_npc_bt/include/dobi_npc_bt/idle_scan.hpp` — Stateful + /person_tracking/tracks
  5 frames 안정 + top track_id customer_id 출력
- `dobi_npc_bt/include/dobi_npc_bt/approach.hpp` — Nav2 액션 코드 제거 +
  /approach/enable Bool 발행 + bh 안정 검사 + lost timeout
- `dobi_npc_bt/src/bt_executor_node.cpp` — IdleScan 등록 시 node 인자 추가
- `dobi_npc_bt/bt_xml/cafe_funnel_v1.xml` — 신규 포트 명시
- `person_tracking_pkg/approach_controller_node.py` — /approach/enable 게이트 추가
- `dobi_npc_emotion/geva_node.py` — cv2.VideoCapture 폐기 → /webcam/image_raw 구독
- `dobi_npc_bringup/launch/dev_common.launch.py` — webcam_master v4l2_camera_node +
  use_webcam arg + person_tracking input_topic 분기

## 2. 핵심 결정

| # | 결정 | 채택 사유 |
|---|---|---|
| D1 | BT 게이트 + controller 유지 | 공통 자산 보존 + funnel 진행 재활용 |
| D2 | 카메라 1 (노트북 내장) v4l2 마스터 + 토픽 분배 | GEVA 와 동시 점유 충돌 해소 |
| D3 | IdleScan 1+ 5 frames | 단발 frame false-positive 차단 |
| D4 | Approach bh≥0.6 5 frames | 거리 기반 안정 종료 |
| D5 (도출) | min_group_size=1 (이미 적용) | D3 solo 모객 정합 |

## 3. 검증 결과

(Phase A / B 체크리스트 표 기입 — Task 9, 10 의 합격 기준)

## 4. 발견 / 함정

(작업 중 발견한 내용)

## 5. 미해결 / 후속

- bh ↔ 실거리 캘리브 (라이브 카메라 2 화각 차이) — §0-A 해제 후
- controller close_threshold (0.999) vs BT bh_threshold (0.6) 책임 경계 재검토
- YOLO 부하 idle 영구 발생 — engaging 진입 시 spawn 분리 별 트랙
- stage 4 Minigame 카메라 (카메라 3) ↔ stage 1-2 카메라 1 ON/OFF 동기 별 트랙

## 6. §0-B 영향

0 — vic_pinky 트리 + RPi 자산 + scripts/run_vic_bringup.sh 등 touch 0.
/bt/cmd_vel 발행 측 게이트만 추가, twist_mux/zlac_driver 변경 없음.
EOF
```

- [ ] **Step 2: 회고 파일 commit**

```bash
git add docs/daily/2026-05-20_person_tracking_bt_integration.md
git commit -m "docs: 2026-05-20 회고 — person_tracking ↔ 모객 BT funnel 통합"
```

---

## Task 12: spec + plan + 회고 묶음 commit 정리 (사용자 push 결정 대기)

**Files:** (없음 — git 정리)

- [ ] **Step 1: spec + plan 미커밋분 commit**

```bash
cd ~/moca
git add docs/superpowers/specs/2026-05-20-person-tracking-bt-integration-design.md
git add docs/superpowers/plans/2026-05-20-person-tracking-bt-integration-plan.md
git commit -m "docs/superpowers: person_tracking ↔ BT funnel 통합 spec + plan"
```

- [ ] **Step 2: git log 확인**

```bash
git log --oneline -10
```

Expected: 본 plan 의 commit 7 개 + spec/plan commit 1 개 = 본 트랙 8 commits.

- [ ] **Step 3: 사용자 push 결정 대기**

```bash
git status
```

Expected: `nothing to commit, working tree clean`. 사용자에게 push 여부 묻기 (push 는 명시적 승인 필요 — git safety policy).

---

## 검증 후 메모리 갱신 권고

검증 통과 시 다음 메모리 갱신:

1. `project_camera_architecture.md` — webcam_master 1단 마스터 정책 + use_webcam arg 추가
2. `feedback_dont_touch_working_code.md` — 본 작업이 cv2.VideoCapture 직접 사용 → 토픽 구독 으로 변경한 예외 사례 (사용자 결정으로 진행) 기록 필요 없으면 skip
3. (신규) `project_approach_enable_gate.md` — `/approach/enable` Bool 게이트 패턴 — 향후 다른 controller (follow_controller 등) 에도 적용 가능 메모

---

## 자체-점검 (writing-plans skill self-review)

**1. Spec coverage:**
- Spec §3 D1 (게이트) → Task 3 + Task 4 ✓
- Spec §3 D2 (카메라 1) → Task 6 ✓
- Spec §3 D3 (IdleScan 5 frames) → Task 2 ✓
- Spec §3 D4 (bh 0.6 5 frames) → Task 3 ✓
- Spec §3 D5 (min_group_size=1) → 이미 적용 (Task 6 의 dev_common 갱신 시 보존) ✓
- Spec §4 데이터 흐름 → Task 9 Phase A + Task 10 Phase B ✓
- Spec §7 에러 처리 → Task 3 (lost_timeout) + Task 4 (PD reset on disable) ✓
- Spec §8 검증 → Task 9 + Task 10 ✓

**2. Placeholder scan:** TBD/TODO/"add error handling" 등 없음 ✓

**3. Type consistency:** `/approach/enable` (std_msgs/Bool), `/customer_pose` (PoseStamped), `/person_tracking/tracks` (PersonTrackArray) — Task 2-7 모두 일관 ✓
