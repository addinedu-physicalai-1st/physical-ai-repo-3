# ddooby_controller

OpenArm 양팔 로봇 기반 핫도그 제조 및 음료 제공 컨트롤러입니다.

## 패키지 구조

`ddooby_controller` 자체가 ROS 2 패키지 루트입니다. OpenArm 관련 외부 의존 패키지는 같은 패키지 내부의 `openarm_vendor/` 아래에 둡니다.

```text
src/controller/ddooby_controller/
├── CMakeLists.txt
├── package.xml
├── include/
├── launch/
│   ├── hotdog_making.launch.py
│   ├── manufacturing_world_gz.launch.py
│   └── manifacture_action_server.launch.py
├── assets/
├── src/
│   ├── manufacturing_* task modules
│   ├── moveit_task_utils.cpp
│   ├── planning_scene_utils.cpp
│   ├── vision_pick_adapter.cpp
│   ├── hotdog_making_node.cpp
│   └── manifacture_action_server_node.cpp
├── tools/
│   ├── legacy_beverage_test/
│   └── physics_contact_tests/
└── openarm_vendor/
    ├── openarm/
    ├── openarm_bimanual_moveit_config/
    ├── openarm_bringup/
    ├── openarm_can/
    ├── openarm_description/
    └── openarm_gazebo/
```

제조 런타임 구조는 아래처럼 분리합니다.

```text
manufacturing_world_gz.launch.py
  - 제조 월드 entrypoint
  - assets/manufacturing_world/layout.json을 기준으로 개별 Gazebo model/entity spawn
  - Gazebo reset, pick/place, 제조 task에서 물체별 entity를 제어할 수 있게 유지

manifacture_action_server_node
  - custom_msg/action/Manifacture.action server
  - item/count를 task queue로 전개
  - count를 하나씩 줄이며 hotdog_making.launch.py task로 전이
  - 모든 task 성공 시 action result success 반환

hotdog_making_node
  - 뉴욕 핫도그 제조 및 coke/coffee 음료 제공 task 실행
  - MoveIt planning, Cartesian path, planning scene, vision pick adapter를 조합

tools/legacy_beverage_test
  - 이전 음료 제조 검증 코드와 scenario/demo node를 보관
  - CMake build/install 대상이 아니며 현재 런타임 backend로 사용하지 않음

tools/physics_contact_tests
  - Gazebo 물리 파라미터 검증용 도구
  - CMake build/install 대상이 아님
```

## 빠른 설치 절차

이미 이 repo를 clone 받은 상태를 기준으로 합니다. 아래 명령어는 repo 안 아무 위치에서 실행해도 `git rev-parse --show-toplevel`로 repo 최상위 경로를 찾아 이동합니다.
ROS 2 Jazzy와 `rosdep`, `colcon`은 먼저 설치되어 있어야 합니다. Gazebo, MoveIt, RViz, ros2_control 관련 의존성은 아래 `rosdep install` 단계에서 package.xml 기준으로 설치됩니다.

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
sudo rosdep init  # 처음 한 번만 실행합니다. 이미 초기화되어 있으면 생략합니다.
rosdep update
rosdep install \
  --from-paths src/controller/ddooby_controller src/controller/ddooby_controller/openarm_vendor \
  --ignore-src \
  -r \
  -y
colcon build \
  --base-paths src/controller/ddooby_controller src/controller/ddooby_controller/openarm_vendor
source install/setup.bash
```

`rosdep install`은 Gazebo, MoveIt, RViz, ros2_control 실행에 필요한 시스템 의존성을 설치합니다. `ddooby_controller` 안에 OpenArm 패키지가 들어있기 때문에 `rosdep install`과 `colcon build` 모두 `ddooby_controller`와 `openarm_vendor`를 함께 지정해야 합니다.

이 절차는 Gazebo 기반 제조 시뮬레이션 실행 기준입니다. OpenArm 실물 로봇을 직접 연결하는 경우에는 별도로 CAN 인터페이스 설정, PCAN-USB Pro FD 드라이버 설치, 모터 ID/제어 모드 세팅이 필요합니다. 해당 절차는 OpenArm 세팅 문서를 기준으로 진행합니다.

## 빠른 실행

로컬 Gazebo 검증은 시작/종료 스크립트를 기준으로 실행합니다.

```bash
TASK=hotdog src/controller/ddooby_controller/modeling/start_local_gazebo_task.sh
src/controller/ddooby_controller/modeling/stop_local_gazebo_task.sh
```

음료 단독 또는 핫도그와 음료 연속 task는 `TASK_SEQUENCE`로 실행합니다.

```bash
TASK_SEQUENCE=coke src/controller/ddooby_controller/modeling/start_local_gazebo_task.sh
TASK_SEQUENCE=coffee src/controller/ddooby_controller/modeling/start_local_gazebo_task.sh
TASK_SEQUENCE=hotdog,coke src/controller/ddooby_controller/modeling/start_local_gazebo_task.sh
```

launch를 직접 호출할 때는 `hotdog_making.launch.py`의 `task` 값을 사용합니다.

```bash
ros2 launch ddooby_controller hotdog_making.launch.py task:=hotdog
ros2 launch ddooby_controller hotdog_making.launch.py task:=coke
ros2 launch ddooby_controller hotdog_making.launch.py task:=coffee
```

## 실행 파일 확인

```bash
ros2 pkg executables ddooby_controller
```

정상적으로 빌드되면 아래 실행 파일들이 보여야 합니다.

```text
ddooby_controller forward_joint_trajectory_bridge_node
ddooby_controller hotdog_making_node
ddooby_controller manifacture_action_server_node
ddooby_controller capture_gazebo_yolo_dataset.py
ddooby_controller gazebo_yolo_pose_node.py
ddooby_controller sync_planning_scene_from_layout.py
```


## Manufacturing Gazebo World

제조 Gazebo world는 커밋된 runtime asset을 기준으로 실행합니다.

```text
src/controller/ddooby_controller/assets/manufacturing_world/layout.json
src/controller/ddooby_controller/assets/manufacturing_world/models/<object_name>/model.sdf
src/controller/ddooby_controller/assets/manufacturing_world/models/<object_name>/meshes/<object_name>.obj
```

제조 world만 실행:

```bash
ros2 launch ddooby_controller manufacturing_world_gz.launch.py
```

MoveGroup/RViz와 함께 실행:

```bash
ros2 launch ddooby_controller manufacturing_world_gz.launch.py with_rviz:=true
```

`with_rviz:=true` 또는 `with_moveit:=true`를 사용하면 export된 SDF collision box가 MoveIt planning scene에도 반영됩니다.

월드 편집 원본과 모델링 작업 메모는 로컬 개발용 `src/controller/ddooby_controller/modeling/` 아래에 있으며, 이 폴더는 `.gitignore` 대상입니다.

## 뉴욕 핫도그 task 검증

`hotdog_making_node`는 `task`, `arm`, `play_to_stage`, `play_to_waypoint` 기준으로 실행 범위를 정합니다. `task`는 제조 단위(`case`, `bread`, `sausage`, `ketchup`, `hotdog`, `coke`, `coffee`)이고, `arm`은 하위 호환을 위해 남겨둔 deprecated 옵션입니다. 일반 제조 흐름은 `task`가 필요한 팔과 단계 순서를 결정합니다.

`play_to_stage`는 `complete`, `home`, `pick`, `work`, `place`, `return_home` 중 하나를 사용합니다. 전체 핫도그 제조 검증은 아래처럼 실행합니다.

먼저 기존 Gazebo/MoveIt/RViz 프로세스가 남아 있지 않게 정리합니다. 중복 world가 떠 있으면 model이 중복 spawn되고 controller 상태가 꼬일 수 있습니다.

```bash
pgrep -af '[r]os2|[g]z sim|[r]viz2|[m]ove_group|[r]obot_state_publisher|[c]ontroller_manager|[h]otdog_making_node|[p]arameter_bridge|[s]pawner'
```

남아 있는 프로세스는 해당 터미널에서 `Ctrl+C`로 종료합니다. 터미널이 이미 닫힌 경우에만 PID를 확인해서 해당 PID만 종료합니다.

```bash
kill <PID>
```

빌드:

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
colcon build \
  --base-paths src/controller/ddooby_controller src/controller/ddooby_controller/openarm_vendor \
  --packages-select openarm_bimanual_moveit_config ddooby_controller \
  --symlink-install
source install/setup.bash
```

터미널 1: Gazebo + MoveGroup + RViz 실행

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
  ros2 launch ddooby_controller manufacturing_world_gz.launch.py with_rviz:=true
```

아래 로그가 보이면 제조 world와 MoveIt planning scene 반영이 끝난 상태입니다.

```text
You can start planning now!
applied 6 collision objects / 16 boxes to MoveIt planning scene
```

터미널 2: 핫도그 전체 task 실행

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 launch ddooby_controller hotdog_making.launch.py task:=hotdog play_to_stage:=complete
```

특정 단계까지만 확인할 때는 `play_to_stage`를 지정합니다.

```bash
ros2 launch ddooby_controller hotdog_making.launch.py task:=bread play_to_stage:=pick
ros2 launch ddooby_controller hotdog_making.launch.py task:=ketchup play_to_stage:=return_home
```

vision pick을 사용할 때는 제조 vision node를 함께 실행하고 `enable_vision_pick:=true`를 전달합니다.

```bash
ros2 launch ddooby_controller hotdog_making.launch.py task:=hotdog enable_vision_pick:=true
```

`ros2 run ddooby_controller hotdog_making_node ...`로 직접 실행하지 않습니다. MoveIt의 `robot_description_semantic` 파라미터가 주입되지 않아 robot model 생성에 실패합니다. 실제 MoveIt 제어는 `hotdog_making.launch.py`를 사용합니다.

실행 중 TCP와 빵 위치를 확인하려면:

```bash
ros2 run tf2_ros tf2_echo world openarm_left_hand_tcp
```

layout 기준 위치를 확인하려면:

```bash
python3 - <<'PY'
import json
from pathlib import Path
layout = Path("src/controller/ddooby_controller/assets/manufacturing_world/layout.json")
for model in json.loads(layout.read_text())["models"]:
    if model["name"] in {"case", "bread1", "sausage", "kachup", "can_coke", "can_coffee"}:
        print(model["xyz"])
PY
```

## 실물 OpenArm 연동

실물 OpenArm에서는 Gazebo를 띄우지 않고, OpenArm MoveIt/ros2_control 스택과 제조 planning scene만 연결합니다. 이 절차는 로봇을 움직이지 않습니다. 실제 제조 이동은 `hotdog_making.launch.py`에서 `dry_run:=false`로 실행할 때 발생하므로, 이동 실행은 작업자가 직접 진행합니다.

CAN 인터페이스는 OpenArm 공식 CAN CLI 절차에 따라 먼저 확인합니다.

```bash
openarm-can-cli -i can0 can_configure
openarm-can-cli -i can0 discover
openarm-can-cli -i can0 can_configure
openarm-can-cli -i can0 show_param

openarm-can-cli -i can1 can_configure
openarm-can-cli -i can1 discover
openarm-can-cli -i can1 can_configure
openarm-can-cli -i can1 show_param
```

실물 MoveIt을 이미 실행해둔 경우에는 제조 collision scene만 반영합니다.

```bash
ros2 launch ddooby_controller manufacturing_openarm.launch.py start_moveit:=false
```

MoveIt/ros2_control까지 함께 시작해야 할 때는 아래처럼 실행합니다. 이 launch 자체는 trajectory를 보내지 않습니다.

```bash
ros2 launch ddooby_controller manufacturing_openarm.launch.py \
  start_moveit:=true \
  use_fake_hardware:=false \
  right_can_interface:=can0 \
  left_can_interface:=can1
```

실물 환경에서 hotdog 제조 노드의 계산만 확인하려면 `use_sim_time:=false`와 `dry_run:=true`를 사용합니다.

```bash
ros2 launch ddooby_controller hotdog_making.launch.py \
  use_sim_time:=false \
  task:=bread \
  play_to_stage:=work \
  dry_run:=true
```

## 주문 action server 실행

`Manifacture.action` goal을 받아 hotdog/coke/coffee task를 실행하려면 action server를 실행합니다.

```bash
ros2 launch ddooby_controller manifacture_action_server.launch.py
```

action server는 item/count를 task queue로 전개하고 각 항목을 `hotdog_making.launch.py task:=hotdog|coke|coffee`로 실행합니다.
