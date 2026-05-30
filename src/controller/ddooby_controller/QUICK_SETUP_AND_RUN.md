# Quick Setup And Run

MOCA 웹 주문을 `ddooby_controller` 제조 action으로 받아서 실물 OpenArm으로 뉴욕 핫도그를 제조하는 빠른 실행 문서.

현재 구현/검증 기준:

```text
web_service 주문
  -> moca_service
  -> custom_msg/action/Manifacture.action
  -> ddooby_controller manifacture action server
  -> hotdog_making_node task:=hotdog use_sim_time:=false
  -> 실물 OpenArm 제조
  -> moca_service 주문 완료 처리
```

현재 제조 가능한 주문 item:

```text
hotdog
coke
coffee
```

현재 실제 제조 동작은 `hotdog`만 구현되어 있다.
`coke`, `coffee`는 주문 item 이름으로는 들어올 수 있지만, 실물 제조 검증은 핫도그 1개 기준으로 한다.

아래 명령은 repo root 기준이다.

```bash
cd "$(git rev-parse --show-toplevel)"
```

## 0. 공통 주의

실물 로봇 제조 연동은 기본 ROS domain을 쓴다.

```bash
export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY
```

`src/service/run_moca_service_native.sh`는 `ROS_DOMAIN_ID`를 안 주면 기본값으로 `99`를 잡는다.
실물 OpenArm bringup은 기본 domain에서 떠 있으므로, 웹 주문 연동 테스트에서는 `moca_service`를 반드시 `ROS_DOMAIN_ID=0`으로 실행한다.

성공했던 실물 테스트의 핵심 설정:

```text
manifacture_action_server.launch.py hotdog_use_sim_time:=false
moca_service ROS_DOMAIN_ID=0
moca_service MOCA_DDOOBY_CONTROLLER_ACTION_NAME=ddooby/manifacture
manufacturing_openarm.launch.py enable_gravity_comp:=true
hotdog_making_node task:=hotdog use_sim_time:=false
```

## 1. 빌드

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
colcon build
source install/setup.bash
```

## 2. 웹/DB 실행

터미널 1.

```bash
cd "$(git rev-parse --show-toplevel)/src/service"

docker compose -f docker-compose.operation.yml up -d
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

정상 예:

```text
moca_db       Up ... (healthy)   0.0.0.0:3307->3306/tcp
web_service   Up ...             0.0.0.0:8000->8000/tcp, 0.0.0.0:9004->9004/tcp
```

헬스 체크:

```bash
curl -k https://127.0.0.1:8000/health
```

정상 응답:

```json
{"status":"ok","service":"web_service"}
```

`moca_service`를 아직 안 띄운 상태에서는 `/api/menu`가 실패할 수 있다.
메뉴 확인은 `moca_service` 실행 후 다시 한다.

## 3. 실물 OpenArm Bringup

터미널 2.

CAN 설정은 로봇 전원/PC 재시작 후 한 번 수행한다.

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

openarm-can-cli -i can0 can_configure
openarm-can-cli -i can1 can_configure
```

제로 캘리브레이션이 필요할 때만 수행한다.
매 실행마다 필수는 아니다.

```bash
openarm-can-zero-position-calibration --canport can0 --arm-side right_arm
openarm-can-zero-position-calibration --canport can1 --arm-side left_arm
```

실물 bringup:

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY

ROS_HOME=/tmp/ros_home ROS_LOG_DIR=/tmp/ros_logs \
ros2 launch ddooby_controller manufacturing_openarm.launch.py \
  start_moveit:=true \
  sync_planning_scene:=true \
  use_fake_hardware:=false \
  hardware_plugin:=openarm_hardware/OpenArmHW \
  robot_controller:=forward_position_controller \
  right_can_interface:=can0 \
  left_can_interface:=can1 \
  return_to_zero_on_activate:=false \
  hold_current_on_activate:=true \
  enable_gravity_comp:=true \
  enable_coriolis_comp:=false
```

이 launch는 실물 로봇을 제어한다.
`return_to_zero_on_activate:=false`, `hold_current_on_activate:=true`로 현재 자세를 유지하면서 controller를 올린다.

ROS graph 확인:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY

ros2 node list | sort
ros2 action list | sort
```

정상적으로 보여야 하는 주요 항목:

```text
/move_group
/controller_manager
/left_forward_joint_trajectory_bridge
/right_forward_joint_trajectory_bridge
/left_joint_trajectory_controller/follow_joint_trajectory
/right_joint_trajectory_controller/follow_joint_trajectory
/left_gripper_controller/gripper_cmd
/right_gripper_controller/gripper_cmd
```

## 4. ddooby 제조 Action Server

터미널 3.

실물 제조에서는 `hotdog_use_sim_time:=false`로 실행한다.

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY
export ROS_HOME=/tmp/ros_home
export ROS_LOG_DIR=/tmp/ros_logs

ros2 launch ddooby_controller manifacture_action_server.launch.py \
  hotdog_use_sim_time:=false
```

정상 로그:

```text
DDooby manufacture action server ready: ddooby/manifacture
```

다른 터미널에서 action 확인:

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY

ros2 action list | grep ddooby
```

정상 출력:

```text
/ddooby/manifacture
```

## 5. moca_service 실행

터미널 4.

웹 주문을 받아서 `/ddooby/manifacture` action goal을 보내는 서비스다.
실물 연동에서는 `ROS_DOMAIN_ID=0`을 반드시 명시한다.

```bash
cd "$(git rev-parse --show-toplevel)/src/service"

export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY

export MOCA_DOBY_CONTROLLER_ROS_ENABLED=false
export MOCA_DDOOBY_CONTROLLER_ROS_ENABLED=true
export MOCA_DDOOBY_CONTROLLER_ACTION_NAME=ddooby/manifacture
export MOCA_DDOOBY_CONTROLLER_ACTION_TIMEOUT_SEC=5.0

./run_moca_service_native.sh
```

정상 로그:

```text
ddooby_controller ROS runtime started node=moca_ddooby_controller action=ddooby/manifacture
order orchestration runtime started
ros domain id:       0
```

`ros domain id: 99`로 보이면 잘못 실행한 것이다.
`Ctrl+C`로 끄고 위 명령처럼 `ROS_DOMAIN_ID=0`을 명시해서 다시 실행한다.

## 6. 메뉴 확인

터미널 5.

```bash
curl -k https://127.0.0.1:8000/api/menu
```

정상 예:

```json
[
  {"id":1,"name":"hotdog","aliases":[],"emoji":"hotdog","price":7000,"hot":false,"shot":false,"ice":false,"milk":false},
  {"id":2,"name":"coke","aliases":[],"emoji":"coke","price":2500,"hot":false,"shot":false,"ice":false,"milk":false},
  {"id":3,"name":"coffee","aliases":[],"emoji":"coffee","price":3500,"hot":false,"shot":false,"ice":false,"milk":false}
]
```

`host.docker.internal:9001` 또는 incomplete tcp read 에러가 나면 `moca_service`가 아직 안 떴거나 재시작 중인 것이다.
몇 초 기다렸다가 다시 확인한다.

## 7. 웹/API로 핫도그 1개 주문

실물 팔이 움직이는 단계다.
로봇 주변을 비우고, 필요하면 바로 정지할 수 있게 준비한 뒤 실행한다.

API로 주문:

```bash
cd "$(git rev-parse --show-toplevel)"

ORDER_ID="$(
  curl -k -sS -X POST https://127.0.0.1:8000/api/orders \
    -H 'Content-Type: application/json' \
    -d '{"channel":"kiosk","payment":"card","items":[{"menu_id":1,"qty":1}]}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["order_id"])'
)"

echo "ORDER_ID=${ORDER_ID}"

curl -k -sS -X POST https://127.0.0.1:8000/api/tables \
  -H 'Content-Type: application/json' \
  -d '{"order_id":'"${ORDER_ID}"',"receive_type":"take_out"}'
```

웹 UI로 주문:

```bash
google-chrome \
  --user-data-dir=/tmp/moca-kiosk-chrome \
  --ignore-certificate-errors \
  https://127.0.0.1:8000/kiosk
```

키오스크에서 `hotdog` 1개를 주문하고 `take_out`으로 확정한다.

## 8. 성공 로그 확인

`moca_service` 터미널에서 확인:

```text
accepted order claimed order_id=...
manufacture command start order_id=...
ddooby manufacture action send action=ddooby/manifacture ... items=[{'name': 'hotdog', 'count': 1}]
ddooby manufacture feedback ... manufacture started: 1 task(s)
ddooby manufacture feedback ... manufacturing hotdog with hotdog_making_node
ddooby manufacture feedback ... completed hotdog run 1/1
ddooby manufacture result succeeded ... message=manufacture completed: 1 task(s)
manufacture completed subscribed order_id=...
order completed order_id=...
```

`ddooby_controller` action server 터미널에서 확인:

```text
Accepted manufacture goal with 1 item entries
Starting hotdog manufacture process: ros2 launch ... hotdog_making.launch.py task:=hotdog use_sim_time:=false
New York hotdog assembly started
Hotdog assembly step 1/5: pick and present case
Hotdog assembly step 2/5: pick and place bread
Hotdog assembly step 3/5: pick and place sausage
Hotdog assembly step 4/5: pick, aim, and squeeze ketchup
Hotdog assembly step 5/5: place completed hotdog at pickup zone
New York hotdog assembly completed
manufacture completed: 1 task(s)
```

DB에서 주문 완료 확인:

```bash
docker exec moca_db mysql -uroot -prootpassword business \
  -e "SELECT order_id, order_status, receive_type, total_price FROM orders ORDER BY order_id DESC LIMIT 5;"
```

성공 기준:

```text
order_status = COMPLETED
receive_type = TAKE_OUT
```

## 9. 직접 제조 노드 실행

웹/서버를 거치지 않고 실물에서 핫도그 제조 노드만 실행할 때:

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY

ROS_HOME=/tmp/ros_home ROS_LOG_DIR=/tmp/ros_logs \
ros2 launch ddooby_controller hotdog_making.launch.py \
  use_sim_time:=false \
  task:=hotdog
```

## 10. Gazebo 제조 world 참고

Gazebo에서 먼저 검증할 때:

```bash
cd "$(git rev-parse --show-toplevel)"
source /opt/ros/jazzy/setup.bash
source install/setup.bash

__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
ros2 launch ddooby_controller manufacturing_world_gz.launch.py with_rviz:=true
```

RViz 없이 Gazebo + MoveIt만 띄울 때:

```bash
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
ros2 launch ddooby_controller manufacturing_world_gz.launch.py with_moveit:=true with_rviz:=false
```

`with_rviz:=false`만 주면 MoveIt도 안 뜰 수 있으므로, 긴 검증에서 RViz만 끄려면 `with_moveit:=true with_rviz:=false`를 같이 준다.

Gazebo 제조 노드:

```bash
ros2 launch ddooby_controller hotdog_making.launch.py task:=hotdog
```

## 11. TF / Pose 확인

엔드이펙터 pose 확인:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 run tf2_ros tf2_echo world openarm_right_hand_tcp
ros2 run tf2_ros tf2_echo world openarm_left_hand_tcp
```

ROS topic 확인:

```bash
ros2 topic echo /joint_states --once
ros2 action list | sort
ros2 node list | sort
```

## 12. 문제 구분

`/ddooby/manifacture`가 안 보일 때:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=0
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY

ros2 action list | grep ddooby
```

안 보이면 `manifacture_action_server.launch.py hotdog_use_sim_time:=false` 터미널을 확인한다.

`moca_service`가 주문은 받는데 제조가 안 시작될 때:

```text
1. moca_service 로그의 ros domain id가 0인지 확인
2. ddooby action server 로그에 Accepted manufacture goal이 찍히는지 확인
3. /ddooby/manifacture action이 같은 ROS_DOMAIN_ID에서 보이는지 확인
```

`moca_service` 로그에 아래처럼 보이면 domain이 잘못된 경우가 많다.

```text
ros domain id:       99
```

실물 테스트에서는 `ROS_DOMAIN_ID=0`으로 다시 실행한다.

웹 `/api/menu`가 예전 커피 메뉴로 보일 때:

```text
1. moca_db 초기 데이터가 최신인지 확인
2. moca_service가 최신 코드로 실행 중인지 확인
3. web_service가 moca_service 9001에 연결되는지 확인
```

메뉴 확인:

```bash
curl -k https://127.0.0.1:8000/api/menu
```

로봇이 움직이지 않거나 execute가 timeout 날 때:

```text
1. manufacturing_openarm.launch.py가 살아 있는지 확인
2. /move_group이 보이는지 확인
3. /right_joint_trajectory_controller/follow_joint_trajectory가 보이는지 확인
4. CAN can0/can1 상태 확인
```

```bash
ip link show can0
ip link show can1
ros2 node list | grep move_group
ros2 action list | grep follow_joint_trajectory
```

## 13. 종료

각 실행 터미널에서 `Ctrl+C`로 종료한다.

종료 대상:

```text
manufacturing_openarm.launch.py
manifacture_action_server.launch.py
run_moca_service_native.sh
web_service / moca_db docker compose
```

Docker 종료:

```bash
cd "$(git rev-parse --show-toplevel)/src/service"
docker compose -f docker-compose.operation.yml down
```

남은 프로세스 확인:

```bash
pgrep -af 'manufacturing_openarm|hotdog_making_node|manifacture_action_server|moca_service|ros2|rviz2|move_group|controller_manager|gz sim'
```

확인한 PID만 종료한다.

```bash
kill <PID>
```

## 14. 로컬 생성 파일

커밋하지 않는 로컬 산출물:

```text
src/service/certs/
src/service/.env
src/service/moca_service/.venv/
src/service/moca_service/.ros_ws/
src/app/admin_gui/.venv/
src/app/order_vui/audio/
build/
install/
log/
```
