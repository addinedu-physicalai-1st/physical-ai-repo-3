# Quick Setup And Run

이 문서는 MOCA 단일 로컬 컴퓨터 개발 환경을 빠르게 설치하고 실행하기 위한 절차입니다.

아래 내용을 위에서부터 차례대로 실행하면 됩니다. `터미널 1`, `터미널 2`처럼 번호가 붙은 실행 명령은 각각 새 터미널에서 실행해 주세요.

이 문서는 repo 안의 `src/controller/ddooby_controller/` 아래에 있습니다.

아래 명령들은 clone 위치와 상관없이 repo root를 자동으로 찾습니다. 각 새 터미널은 repo 안 아무 위치에서 열고 실행하면 됩니다.

```bash
cd "$(git rev-parse --show-toplevel)"
```

이 문서가 있는 디렉터리에서 터미널을 열었다면 `cd ../../..`로 repo root에 갈 수도 있습니다.

## 빠른 설치

### 1. 시스템 패키지 설치

ROS 2 Jazzy가 이미 설치되어 있다는 전제입니다.

```bash
sudo apt update
sudo apt install -y \
  docker.io \
  docker-compose-v2 \
  python3-pip \
  python3-venv \
  python3-pygame \
  libxcb-cursor0 \
  ros-jazzy-behaviortree-cpp \
  ros-jazzy-navigation2 \
  ros-jazzy-nav2-bringup \
  ros-jazzy-nav2-amcl \
  ros-jazzy-nav2-msgs
```

Docker를 일반 사용자로 실행할 수 있게 설정합니다.

```bash
sudo usermod -aG docker "$USER"
newgrp docker
docker ps
```

`docker ps`에서 권한 문제가 계속 나면 현재 터미널에서는 아래처럼 실행합니다.

```bash
sg docker -c 'docker ps'
```

### 2. Python 의존성 설치

```bash
cd "$(git rev-parse --show-toplevel)"

python3 -m pip install --user --break-system-packages -r src/controller/doby_controller/requirements.txt
python3 -m pip install --user --break-system-packages -r src/app/admin_gui/requirements.txt

python3 -m pip uninstall --break-system-packages -y numpy opencv-python opencv-contrib-python
```

설치 확인:

```bash
python3 - <<'PY'
for m in ["edge_tts", "pygame", "mediapipe", "PyQt6", "fastapi", "uvicorn", "pydantic", "ultralytics", "boxmot"]:
    try:
        __import__(m)
        print(m, "OK")
    except Exception as e:
        print(m, "MISSING", e)

import numpy, cv2
print("numpy", numpy.__version__)
print("cv2", cv2.__version__)
PY
```

### 3. 모델과 필수 디렉터리 준비

```bash
cd "$(git rev-parse --show-toplevel)/src/controller/doby_controller"

mkdir -p src/moca_gazebo/models
bash scripts/download_models.sh

mkdir -p src/dobi_npc/person_tracking_pkg/models
curl -L \
  -o src/dobi_npc/person_tracking_pkg/models/pose_landmarker_lite.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task
```

### 4. doby_controller ROS 빌드

```bash
cd "$(git rev-parse --show-toplevel)/src/controller/doby_controller"

source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

### 5. ddooby_controller 음료 제조 시뮬레이션 빌드

주문과 Gazebo 음료 제조 테스트 노드를 연결하려면 `ddooby_controller`도 빌드되어 있어야 합니다.

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
rosdep update
rosdep install \
  --from-paths src/controller/ddooby_controller src/controller/ddooby_controller/openarm_vendor \
  --ignore-src \
  -r \
  -y
colcon build \
  --base-paths src/controller/ddooby_controller src/controller/ddooby_controller/openarm_vendor \
  --symlink-install
source install/setup.bash
```

### 6. web_service HTTPS 설정

개발용 self-signed 인증서를 생성합니다.

```bash
cd "$(git rev-parse --show-toplevel)/src/service"

mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout certs/key.pem \
  -out certs/cert.pem \
  -days 365 \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

cat > .env <<'EOF'
WEB_SERVICE_SSL_CERT=/certs/cert.pem
WEB_SERVICE_SSL_KEY=/certs/key.pem
EOF
```

`web_service`가 mount하는 오디오 디렉터리도 준비합니다.

```bash
cd "$(git rev-parse --show-toplevel)"
mkdir -p src/app/order_vui/audio
```

### 7. admin_gui venv 준비

```bash
cd "$(git rev-parse --show-toplevel)/src/app/admin_gui"

python3 -m venv --system-site-packages .venv
./.venv/bin/python -m pip install -r requirements.txt
```

## 빠른 실행

아래는 터미널을 나누어 실행합니다.

### 터미널 1. ROS bringup

```bash
cd "$(git rev-parse --show-toplevel)/src/controller/doby_controller"

source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=99
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_LOCALHOST_ONLY=1
export MPLCONFIGDIR=/tmp/moca_matplotlib

# 로컬 감정 GIF 백업이 있는 경우만 본인 경로로 설정합니다.
# export MOCA_GIF_DIR="$HOME/path/to/pinky_emotion/emotion"

ros2 launch dobi_npc_bringup dev_common.launch.py fullscreen:=false initial_mode:=idle
```

### 터미널 2. Gazebo 제조 world

커밋된 `assets/manufacturing_world/layout.json`과 `assets/manufacturing_world/models/`를 기준으로 제조 Gazebo world를 실행합니다. 각 물체는 Gazebo 안에서 개별 model/entity로 spawn됩니다.

실행 전에 기존 Gazebo/MoveIt/RViz 프로세스가 남아 있지 않은지 확인합니다. 중복 world가 떠 있으면 model이 중복 spawn되고 controller 상태가 꼬일 수 있습니다.

```bash
pgrep -af '[r]os2|[g]z sim|[r]viz2|[m]ove_group|[r]obot_state_publisher|[c]ontroller_manager|[h]otdog_making_node|[p]arameter_bridge|[s]pawner'
```

남아 있으면 해당 실행 터미널에서 `Ctrl+C`로 종료합니다. 터미널이 이미 닫힌 경우에만 PID를 확인해서 해당 PID만 종료합니다.

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
  ros2 launch ddooby_controller manufacturing_world_gz.launch.py
```

Gazebo 제조 world, MoveGroup, RViz를 한 번에 띄우고 RViz에서 로봇 제어를 확인하려면 아래처럼 실행합니다. 이 경우 터미널 3, 터미널 4는 따로 실행하지 않아도 됩니다.
`layout.json`과 각 `model.sdf`의 collision box도 MoveIt planning scene에 자동 반영되므로 RViz MotionPlanning 화면에서 제조 물체를 장애물로 볼 수 있습니다.

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
  ros2 launch ddooby_controller manufacturing_world_gz.launch.py with_rviz:=true
```

아래 로그가 보이면 MoveIt planning scene까지 준비된 상태입니다.

```text
You can start planning now!
applied 6 collision objects / 16 boxes to MoveIt planning scene
```

기존 테스트 station만 독립적으로 실행하고 싶을 때는 아래 launch도 사용할 수 있습니다.

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
  ros2 launch ddooby_controller beverage_station_gz.launch.py
```

### 터미널 3. MoveGroup

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch openarm_gazebo move_group_gz.launch.py
```

### 터미널 4. RViz

RViz는 필수는 아니지만, Gazebo 제조 task 동작을 관찰하기 위해 함께 켜는 것을 권장합니다.

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
  ros2 launch openarm_gazebo moveit_rviz_gz.launch.py
```

### 추가 터미널. ddooby_controller 제조 action server

`moca_service`가 제조 요청을 보낼 `custom_msg/action/Manifacture.action` server입니다. Gazebo world와 MoveGroup이 먼저 떠 있어야 기본 backend에서 커피/에이드 제조 테스트 노드가 실제 Gazebo 모션을 실행할 수 있습니다.

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=99
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY

ros2 launch ddooby_controller manifacture_action_server.launch.py
```

실제 제조 task-node skeleton만 확인하려면 아래처럼 실행합니다. 이 모드는 아직 실제 MoveIt 경로를 수행하지 않고, `hotdog_making_node`와 `drink_serving_node`의 시나리오 단계만 실행합니다.

```bash
ros2 launch ddooby_controller manifacture_action_server.launch.py execution_backend:=scenario_task_nodes
```

정상 로그:

```text
DDooby manufacture action server ready: ddooby/manifacture
```

### 추가 터미널. 뉴욕 핫도그 pick 검증

터미널 2에서 `manufacturing_world_gz.launch.py with_rviz:=true`를 실행하고, planning scene sync 로그까지 확인한 뒤 실행합니다.

계산만 먼저 확인:

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 launch ddooby_controller hotdog_making.launch.py target:=bread arm:=left stop_after_stage:=pick dry_run:=true
```

정상 로그 예:

```text
Target 'bread': xyz=[0.313 0.183 0.303], size=[0.150 0.050 0.025], principal=[1.000 0.000 0.000], closing=[-0.000 1.000 0.000]
```

실제 빵 pick 실행:

```bash
ros2 launch ddooby_controller hotdog_making.launch.py target:=bread arm:=left stop_after_stage:=pick
```

주의:

```text
ros2 run ddooby_controller hotdog_making_node ...
```

위 방식으로 직접 실행하지 않습니다. MoveIt의 `robot_description_semantic` 파라미터가 주입되지 않아 robot model 생성에 실패합니다. 실제 MoveIt 제어는 `hotdog_making.launch.py`를 사용합니다.

엔드이펙터 위치 확인:

```bash
ros2 run tf2_ros tf2_echo world openarm_left_hand_tcp
```

빵 layout 위치 확인:

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


### 터미널 5. web_service, moca_db

```bash
cd "$(git rev-parse --show-toplevel)/src/service"

sg docker -c 'docker compose -f docker-compose.operation.yml up -d'
curl -k https://localhost:8000/health
```

정상 응답:

```json
{"status":"ok","service":"web_service"}
```

### 터미널 6. moca_service

`moca_service`는 주문 확정 후 제조가 필요한 항목을 `custom_msg/action/Manifacture.action` goal로 `ddooby_controller`에 보냅니다. 현재 임시 매핑은 아래와 같습니다.

```text
커피류   -> espresso_cup -> Gazebo 음료 제조 테스트 노드 실행
에이드류 -> ade_cup      -> Gazebo 음료 제조 테스트 노드 실행
핫도그류 -> temporary hotdog placeholder
```

웹 주문에서 커피/에이드를 고르면 action server가 `beverage_making_test_node`를 실행합니다. 제조 노드는 시작할 때 Gazebo 컵/스틱 오브젝트를 초기 위치로 reset하고, 완료되면 action result로 성공/실패를 반환합니다.

```bash
cd "$(git rev-parse --show-toplevel)/src/service"

export MOCA_DOBY_CONTROLLER_ROS_ENABLED=false
export MOCA_DDOOBY_CONTROLLER_ROS_ENABLED=true
export MOCA_DDOOBY_CONTROLLER_ACTION_NAME=ddooby/manifacture
export MOCA_DDOOBY_CONTROLLER_ACTION_TIMEOUT_SEC=5.0
export ROS_DOMAIN_ID=99
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY

./run_moca_service_native.sh
```

주문/서비스만 테스트하고 제조 action을 실행하지 않으려면 아래처럼 끕니다.

```bash
export MOCA_DDOOBY_CONTROLLER_ROS_ENABLED=false
./run_moca_service_native.sh
```

### 터미널 7. 키오스크 브라우저

```bash
google-chrome \
  --user-data-dir=/tmp/moca-kiosk-chrome \
  --kiosk \
  --ignore-certificate-errors \
  https://localhost:8000/kiosk
```

브라우저에서 `NET::ERR_CERT_AUTHORITY_INVALID`가 뜨면 개발용 self-signed 인증서 때문입니다. 로컬 테스트에서는 `고급`을 눌러 계속 진행하면 됩니다.

### 터미널 8. admin_gui

```bash
cd "$(git rev-parse --show-toplevel)/src/app/admin_gui"

ADMIN_GUI_HOST=127.0.0.1 ./.venv/bin/python main.py
```


## 웹 주문-가제보 제조 시뮬레이션 검증

목표 흐름은 아래입니다.

```text
웹/키오스크 주문
  -> moca_service 주문확인
  -> Manifacture.action goal 전송
  -> ddooby_controller action server
  -> beverage_making_test_node 실행
  -> Gazebo 제조 시뮬레이션 완료
  -> Manifacture.action result 성공
  -> moca_service 주문 완료
```

### 1. 실행 상태 확인

아래 프로세스가 떠 있어야 합니다.

```bash
pgrep -af 'beverage_station_gz|gz sim|move_group_gz|move_group|manifacture_action_server|moca_service'
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

ROS action server 확인:

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash

export ROS_DOMAIN_ID=99
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
unset ROS_LOCALHOST_ONLY

ros2 action list
```

정상 출력:

```text
/ddooby/manifacture
```

web_service 확인:

```bash
curl -k https://localhost:8000/health
```

정상 응답:

```json
{"status":"ok","service":"web_service"}
```

### 2. 웹 UI에서 주문

키오스크를 열고 커피 또는 에이드 메뉴를 주문합니다.

```bash
google-chrome \
  --user-data-dir=/tmp/moca-kiosk-chrome \
  --kiosk \
  --ignore-certificate-errors \
  https://localhost:8000/kiosk
```

검증용 추천 메뉴:

```text
아메리카노   -> espresso_cup 제조 테스트
딸기스무디   -> ade_cup 제조 테스트
```

`doby_controller` 서빙을 끈 상태에서는 `take_out`으로 주문하세요. `dine_in`으로 주문하면 제조 완료 후 서빙 단계로 넘어가며, 서빙 ROS 런타임이 꺼져 있으면 주문 전체가 실패 처리될 수 있습니다. 제조 action result 검증 자체는 제조 완료 시점에 이미 성공입니다.

### 3. API로 같은 흐름 재현

브라우저 대신 아래 명령으로 같은 흐름을 재현할 수 있습니다. `menu_id=1`은 아메리카노라서 `espresso_cup` Gazebo 제조 테스트가 실행됩니다.

```bash
cd "$(git rev-parse --show-toplevel)"

ORDER_ID="$(
  curl -k -sS -X POST https://localhost:8000/api/orders \
    -H 'Content-Type: application/json' \
    -d '{"channel":"kiosk","payment":"card","items":[{"menu_id":1,"qty":1}]}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["order_id"])'
)"

curl -k -sS -X POST https://localhost:8000/api/tables \
  -H 'Content-Type: application/json' \
  -d '{"order_id":'"${ORDER_ID}"',"receive_type":"take_out"}'
```

에이드 경로를 검증하려면 주문 생성 payload의 `menu_id`를 `7`로 바꿉니다.

### 4. 성공 로그 확인

`moca_service` 터미널에서 아래 흐름을 확인합니다.

```text
accepted order claimed ...
manufacture command start ...
ddooby manufacture action send ...
ddooby manufacture feedback ... manufacturing ...
ddooby manufacture result succeeded ...
manufacture completed subscribed ...
order completed ...
```

`ddooby_controller` action server 터미널에서 아래 흐름을 확인합니다.

```text
Accepted manufacture goal ...
manufacturing ... with espresso_cup 또는 ade_cup ...
Resetting Gazebo model with CLI ...
Starting beverage test process ...
Beverage task manager sequence completed
completed ... run 1/1
manufacture completed: 1 temporary task(s)
```

DB에서 주문 완료 상태를 확인합니다.

```bash
docker exec moca_db mysql -uroot -prootpassword business \
  -e "SELECT order_id, order_status, receive_type, table_id, total_price FROM orders WHERE order_id=${ORDER_ID};"
```

성공 기준:

```text
order_status = COMPLETED
receive_type = TAKE_OUT
```

### 5. 빠른 문제 구분

- `/ddooby/manifacture`가 안 보이면 action server 터미널을 확인합니다.
- `Starting beverage test process` 이후 진행이 없으면 Gazebo station과 MoveGroup이 떠 있는지 확인합니다.
- `Gazebo set pose service` 또는 reset 관련 실패가 보이면 Gazebo world가 완전히 올라오기 전에 주문한 것입니다. Gazebo controller spawner가 모두 끝난 뒤 다시 주문합니다.
- `ddooby manufacture result succeeded`는 보이는데 주문이 실패하면 제조 이후 단계 문제입니다. `dine_in` 주문에서 `doby_controller` 서빙이 꺼져 있을 때 흔히 발생합니다. 제조 연동 검증은 성공으로 봅니다.

## 빠른 종료

실행했던 터미널을 열어둔 상태라면 아래 순서대로 종료합니다.

### 1. 네이티브 프로세스 종료

아래 터미널에서 각각 `Ctrl+C`를 누릅니다.

```text
터미널 1. ROS bringup
터미널 2. Gazebo 제조 world
터미널 3. MoveGroup
터미널 4. RViz
터미널 6. moca_service
터미널 8. admin_gui
```

키오스크 브라우저는 창을 닫으면 됩니다.

### 2. Docker 서비스 종료

```bash
cd "$(git rev-parse --show-toplevel)/src/service"
sg docker -c 'docker compose -f docker-compose.operation.yml down'
```

### 3. 종료 확인

Docker 컨테이너가 남아 있는지 확인합니다.

```bash
sg docker -c 'docker ps --format "{{.Names}} {{.Status}}"'
```

아무 것도 출력되지 않으면 현재 실행 중인 Docker 컨테이너가 없는 상태입니다.

프로젝트 관련 프로세스가 남아 있는지 확인합니다.

```bash
pgrep -af 'doby_controller|ddooby_controller|moca_service|admin_gui|dobi_npc|web_service|ros2|rviz|gazebo|gz sim'
```

아무 것도 출력되지 않으면 프로젝트 관련 host 프로세스가 종료된 상태입니다.

주요 포트가 닫혔는지 확인합니다.

```bash
ss -ltnp | grep -E ':8000|:9001|:9002|:9004|:3307' || true
```

아무 것도 출력되지 않으면 `web_service`, `moca_service`, `admin_gui`, `moca_db` 관련 포트가 닫힌 상태입니다.

### 4. 프로세스가 남아 있을 때

정상 종료가 안 된 프로세스가 있으면 먼저 PID를 확인합니다.

```bash
pgrep -af 'doby_controller|ddooby_controller|moca_service|admin_gui|dobi_npc|web_service|ros2|rviz|gazebo|gz sim'
```

확인한 PID만 지정해서 종료합니다.

```bash
kill <PID>
```

예를 들어 `admin_gui`가 `./.venv/bin/python main.py`로 남아 있다면 해당 PID만 종료합니다.

```bash
kill <admin_gui_PID>
```

그래도 종료되지 않는 경우에만 마지막 수단으로 강제 종료합니다.

```bash
kill -9 <PID>
```

## 참고

### `docker-compose-plugin` 패키지를 찾을 수 없는 경우

Ubuntu 환경에 따라 `docker-compose-plugin` 대신 `docker-compose-v2`를 설치해야 합니다.

```bash
sudo apt install -y docker-compose-v2
```

### `python3 -m pip`가 없는 경우

```bash
sudo apt install -y python3-pip
```

### Chrome 인증서 경고

현재 문서는 로컬 개발용 self-signed 인증서를 사용합니다. 그래서 `https://localhost:8000/kiosk` 접속 시 인증서 경고가 뜰 수 있습니다.

실제 장기 테스트나 스마트폰 연동까지 고려하면 `mkcert`로 로컬 CA를 구성하는 편이 더 안전하고 편합니다.

### assets와 models 디렉터리 구분

커밋해야 하는 작은 시뮬레이션 자산은 `assets/`에 둡니다. 예를 들어 `ddooby_controller`의 컵, 테이블, 스틱 SDF 자산은 `src/controller/ddooby_controller/assets/` 아래에 있습니다.

`models/`는 MediaPipe, YOLO, LLM weight처럼 다운로드되는 AI 모델 산출물 용도로 보고 기본적으로 git ignore합니다.

## 보안 영향 검토

### 결론

현재까지 진행한 설치와 실행이 Google 계정, 브라우저 계정, SSH key, API key 같은 민감정보를 직접 읽거나 업로드하는 흐름은 확인되지 않았습니다.

다만 개발 편의를 위해 로컬 PC 보안 모델에 영향을 주는 설정이 있으므로 아래 항목은 주의해야 합니다.

### 주의할 점

- Docker group 권한을 부여했습니다. `docker` 그룹 사용자는 Docker 데몬을 통해 사실상 root에 가까운 권한을 얻을 수 있습니다.
- `web_service`, `moca_service`, `moca_db` 일부 포트가 `0.0.0.0`로 열립니다. 같은 네트워크의 다른 장비에서 접근할 수 있으므로 공용 Wi-Fi에서는 실행하지 않는 편이 안전합니다.
- MySQL 계정은 개발용 기본값입니다. 외부 네트워크에 노출되는 환경에서는 비밀번호를 반드시 변경해야 합니다.
- `src/service/certs/key.pem`은 로컬 개발용 private key입니다. 외부에 공유하거나 커밋하면 안 됩니다.
- Chrome을 `--ignore-certificate-errors`로 실행하면 인증서 검증을 우회합니다. 이 옵션은 별도 프로필과 `localhost` 테스트 주소에만 사용하고, 일반 웹 브라우징이나 Google 로그인에는 사용하지 않는 것이 안전합니다.
- `python3 -m pip install --user --break-system-packages`는 사용자 Python 환경에 패키지를 설치하므로 ROS Python 환경과 충돌할 수 있습니다. 그래서 pip로 설치된 `numpy`, `opencv-python`, `opencv-contrib-python`은 제거하고 ROS/Ubuntu 시스템 버전을 사용하도록 정리했습니다.
- 설치 과정에서 Docker image, apt 패키지, pip 패키지, MediaPipe 모델을 인터넷에서 다운로드합니다. 외부 서비스가 접속 IP와 일반 다운로드 요청 로그를 볼 수는 있지만, Google 계정 정보를 제공하는 흐름은 아닙니다.

### 로컬 생성 파일

아래 파일과 디렉터리는 로컬 실행을 위해 생성되며, 커밋하지 않는 것이 좋습니다.

```text
src/service/certs/
src/service/.env
src/app/admin_gui/.venv/
src/app/order_vui/audio/
src/controller/doby_controller/build/
src/controller/doby_controller/install/
src/controller/doby_controller/log/
src/controller/doby_controller/src/moca_gazebo/models/
src/controller/doby_controller/src/dobi_npc/dobi_npc_emotion/models/
src/controller/doby_controller/src/dobi_npc/dobi_npc_minigame/models/
src/controller/doby_controller/src/dobi_npc/person_tracking_pkg/models/
```

### 권장 운영 방식

- 로컬 개발 중에는 `localhost` 또는 신뢰할 수 있는 사설망에서만 실행합니다.
- Chrome 인증서 우회 옵션은 키오스크 테스트 전용 별도 프로필에만 사용합니다.
- 장기 테스트 또는 스마트폰 연동에는 `mkcert`로 로컬 CA를 구성합니다.
- 공용 네트워크에서 실행해야 한다면 방화벽으로 `8000`, `9001`, `9002`, `9004`, `3307` 접근 범위를 제한합니다.
