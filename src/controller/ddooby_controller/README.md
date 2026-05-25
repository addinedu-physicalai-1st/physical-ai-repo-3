# ddooby_controller

OpenArm 양팔 로봇 기반 음료 제조 테스트 컨트롤러입니다.

## 패키지 구조

`ddooby_controller` 자체가 ROS 2 패키지 루트입니다. OpenArm 관련 외부 의존 패키지는 같은 패키지 내부의 `openarm_vendor/` 아래에 둡니다.

```text
src/controller/ddooby_controller/
├── CMakeLists.txt
├── package.xml
├── include/
├── launch/
│   ├── beverage_making_test.launch.py
│   ├── beverage_station_gz.launch.py
│   ├── hotdog_making.launch.py
│   ├── manufacturing_world_gz.launch.py
│   └── manifacture_action_server.launch.py
├── assets/
├── src/
│   ├── beverage_making_test_node.cpp
│   ├── drink_serving_node.cpp
│   ├── hotdog_making_node.cpp
│   └── manifacture_action_server_node.cpp
└── openarm_vendor/
    ├── openarm/
    ├── openarm_bimanual_moveit_config/
    ├── openarm_bringup/
    ├── openarm_can/
    ├── openarm_description/
    └── openarm_gazebo/
```

현재 `beverage_making_test_node`는 주문-제조 연동 검증용 임시 backend입니다. 실제 제조 준비 구조는 아래처럼 분리합니다.

```text
manufacturing_world_gz.launch.py
  - 제조 월드 entrypoint
  - assets/manufacturing_world/layout.json을 기준으로 개별 Gazebo model/entity spawn
  - Gazebo reset, pick/place, 제조 task에서 물체별 entity를 제어할 수 있게 유지

manifacture_action_server_node
  - custom_msg/action/Manifacture.action server
  - item/count를 task queue로 전개
  - count를 하나씩 줄이며 hotdog/drink task로 전이
  - 모든 task 성공 시 action result success 반환

hotdog_making_node
  - 뉴욕 핫도그 1개 제조 task skeleton
  - case -> bread -> sausage -> ketchup -> pickup zone 순서

drink_serving_node
  - 음료 1개 제공 task skeleton
  - fridge open -> drink pick -> pickup zone 순서
```

`manifacture_action_server_node`의 `execution_backend` 파라미터는 두 가지입니다.

```text
temporary_beverage_test  기존 Gazebo 음료 제조 테스트 backend 유지
scenario_task_nodes      hotdog_making_node/drink_serving_node skeleton 실행
```

기본값은 기존 웹 주문-가제보 검증을 깨지 않기 위해 `temporary_beverage_test`입니다.

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

이 절차는 Gazebo 기반 음료 제조 시뮬레이션 실행 기준입니다. OpenArm 실물 로봇을 직접 연결하는 경우에는 별도로 CAN 인터페이스 설정, PCAN-USB Pro FD 드라이버 설치, 모터 ID/제어 모드 세팅이 필요합니다. 해당 절차는 OpenArm 세팅 문서를 기준으로 진행합니다.

## 빠른 실행

아래 명령어를 순서대로 실행하면 됩니다. `터미널 1`부터 `터미널 4`까지는 각각 별도의 새 터미널에서 실행해 주세요.

이미 Gazebo, MoveGroup, RViz, 테스트 노드를 실행했던 상태라면 먼저 기존 프로세스가 남아 있지 않은지 확인합니다. 특히 `move_group`이 2개 이상 떠 있으면 Gazebo가 움직이지 않거나 trajectory 실행 상태가 꼬일 수 있습니다.

```bash
pgrep -af 'ddooby_controller|openarm_gazebo|move_group|rviz2|gz sim|ros2 launch'
```

남아 있는 프로세스가 있다면 각 실행 터미널에서 `Ctrl+C`로 종료한 뒤 다시 실행합니다. 터미널을 닫았는데도 orphan 프로세스가 남은 경우에는 PID를 확인한 뒤 해당 PID만 종료합니다.

```bash
kill <PID>
```

빌드:

빠른 설치 절차에서 이미 빌드했다면 이 단계는 생략할 수 있습니다.

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
colcon build \
  --base-paths src/controller/ddooby_controller src/controller/ddooby_controller/openarm_vendor
source install/setup.bash
```

`ddooby_controller` 안에 OpenArm 패키지가 들어있기 때문에 `--base-paths`에 `ddooby_controller`와 `openarm_vendor`를 모두 지정해야 합니다.

터미널 1: Gazebo station 실행

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
  ros2 launch ddooby_controller beverage_station_gz.launch.py
```

터미널 2: MoveGroup 실행

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch openarm_gazebo move_group_gz.launch.py
```

MoveGroup 로그에 `You can start planning now!`가 출력된 뒤 다음 단계를 실행합니다.

터미널 3: RViz 실행

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
  ros2 launch openarm_gazebo moveit_rviz_gz.launch.py
```

터미널 4: 음료 제조 테스트 실행

에스프레소 원액 컵을 사용할 때:

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch ddooby_controller beverage_making_test.launch.py ingredient_model:=espresso_cup
```

에이드 원액 컵을 사용할 때:

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch ddooby_controller beverage_making_test.launch.py ingredient_model:=ade_cup
```

특정 구간만 실행하려면 `start_step`, `end_step`을 지정합니다.

```bash
ros2 launch ddooby_controller beverage_making_test.launch.py \
  ingredient_model:=espresso_cup \
  start_step:=stir_grasp \
  end_step:=stir_motion
```

젓기부터 픽업존 배치까지 실행하려면:

```bash
ros2 launch ddooby_controller beverage_making_test.launch.py \
  ingredient_model:=espresso_cup \
  start_step:=stir_grasp \
  end_step:=pickup_place
```

지원되는 구분 동작 이름:

```text
cup_ready, cup_pre_grasp, cup_open, cup_grasp, cup_close, cup_lift,
water_pour, water_clear, ingredient_pour_place,
stir_grasp, stir_pick_lift, stir_stick_close, stir_hover, stir_motion,
stir_cleanup, pickup_place
```

## 실행 파일 확인

```bash
ros2 pkg executables ddooby_controller
```

정상적으로 빌드되면 아래 실행 파일들이 보여야 합니다.

```text
ddooby_controller beverage_making_test_node
ddooby_controller drink_serving_node
ddooby_controller hotdog_making_node
ddooby_controller manifacture_action_server_node
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

## 뉴욕 핫도그 빵 Pick 검증

`hotdog_making_node`의 첫 실제 MoveIt 검증 단계는 `bread_pick`입니다. 이 단계는 `assets/manufacturing_world/layout.json`과 `models/bread/model.sdf`의 collision box를 읽어서 빵의 주축을 계산하고, 주축 기준으로 파지 방향을 정합니다.

현재 world 기준 빵 model 이름은 `bread`입니다. `bread1`, `bread2`, `bread3`는 사용하지 않습니다.

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

터미널 2: 빵 pick 계산만 확인

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 launch ddooby_controller hotdog_making.launch.py active_step:=bread_pick dry_run:=true
```

정상 로그 예:

```text
Target 'bread': xyz=[0.313 0.183 0.303], size=[0.150 0.050 0.025], principal=[1.000 0.000 0.000], closing=[-0.000 1.000 0.000]
```

터미널 2: 실제 빵 pick 실행

```bash
ros2 launch ddooby_controller hotdog_making.launch.py active_step:=bread_pick
```

`ros2 run ddooby_controller hotdog_making_node ...`로 직접 실행하지 않습니다. MoveIt의 `robot_description_semantic` 파라미터가 주입되지 않아 robot model 생성에 실패합니다. 실제 MoveIt 제어는 `hotdog_making.launch.py`를 사용합니다.

실행 중 TCP와 빵 위치를 확인하려면:

```bash
ros2 run tf2_ros tf2_echo world openarm_left_hand_tcp
```

빵의 layout 기준 위치를 확인하려면:

```bash
python3 - <<'PY'
import json
from pathlib import Path
layout = Path("src/controller/ddooby_controller/assets/manufacturing_world/layout.json")
for model in json.loads(layout.read_text())["models"]:
    if model["name"] == "bread":
        print(model["xyz"])
PY
```

`hotdog_making.launch.py`는 pre-grasp 도달 뒤 TCP x/y와 목표 x/y의 오차를 검사합니다. 기본 허용 오차는 `0.03m`입니다. approximate IK는 목표 x/y를 크게 놓칠 수 있어서 기본 비활성화되어 있습니다.

## 실제 제조 skeleton 실행

현재 제조 시나리오 골격만 빠르게 확인하려면 action server를 아래처럼 실행합니다.

```bash
ros2 launch ddooby_controller manifacture_action_server.launch.py execution_backend:=scenario_task_nodes
```

이 모드에서는 `Manifacture.action` goal을 받으면 커피/에이드/음료 계열은 `drink_serving_node`, 핫도그 계열은 `hotdog_making_node`를 실행합니다. 각 task node는 아직 실제 MoveIt 경로를 수행하지 않고, 최종 제조 단계의 순서를 로그로 실행한 뒤 success marker를 남깁니다.

기존 Gazebo 음료 제조 테스트를 계속 검증하려면 기본값 그대로 실행합니다.

```bash
ros2 launch ddooby_controller manifacture_action_server.launch.py
```
