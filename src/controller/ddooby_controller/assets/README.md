# ddooby_controller Runtime Assets

이 폴더는 `ddooby_controller` 제조 Gazebo world가 실행할 때 사용하는 runtime asset을 담습니다.

## 구조

```text
assets/
├── manufacturing_world/
│   ├── layout.json
│   └── models/
│       └── <object_name>/
│           ├── model.config
│           ├── model.sdf
│           └── meshes/
│               ├── <object_name>.obj
│               └── <object_name>.mtl
├── cup/
├── mixing_cup_open/
├── pickup_zone/
├── stir_stick/
├── stir_stick_holder/
└── table/
```

`manufacturing_world/layout.json`은 Gazebo에 spawn할 model 목록과 pose를 정의합니다. `manufacturing_world/models/<object_name>/` 아래의 SDF/OBJ/MTL 파일은 Gazebo visual/collision에 사용됩니다.

## 실행

제조 Gazebo world만 실행:

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch ddooby_controller manufacturing_world_gz.launch.py
```

Gazebo, MoveGroup, RViz를 함께 실행:

```bash
cd "$(git rev-parse --show-toplevel)"

source /opt/ros/jazzy/setup.bash
source install/setup.bash
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only \
  ros2 launch ddooby_controller manufacturing_world_gz.launch.py with_rviz:=true
```

RViz 없이 MoveGroup만 함께 실행:

```bash
ros2 launch ddooby_controller manufacturing_world_gz.launch.py with_moveit:=true
```

`with_moveit:=true` 또는 `with_rviz:=true`를 사용하면 `layout.json`과 각 `model.sdf`의 collision box가 MoveIt planning scene에도 반영됩니다. RViz MotionPlanning 화면에서 제조 테이블, 트레이, 빵, 케첩 같은 물체가 collision object로 보이고, MoveIt planning도 이 물체들을 장애물로 고려합니다.

## 현재 Spawn 모델

현재 제조 world의 주요 model은 아래와 같습니다.

```text
openarm_bimanual
table
pickup_zone
tray_stand
tray
kachup
bread
```

## 수정 주의

`assets/manufacturing_world/layout.json`과 `assets/manufacturing_world/models/`는 월드 편집 원본에서 export된 결과물입니다. 일반 실행자는 직접 수정하지 않습니다.

월드 편집 원본과 모델링 작업 메모는 로컬 개발용 `src/controller/ddooby_controller/modeling/` 아래에 있으며, 이 폴더는 `.gitignore` 대상입니다.
