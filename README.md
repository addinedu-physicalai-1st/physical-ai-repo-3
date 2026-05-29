# MOCA

음성 주문, 상품 제조·서빙·정리, 고객 안내와 호객까지 수행하는 자율주행 카페 로봇 통합 서비스 프로젝트입니다.

## Core Features

- **음성 기반 주문 시스템**: 키오스크 wake word ("주문할게요") 및 폰 푸시-투-토크(Push-to-Talk) 지원
- **로봇 기반 상품 제조와 서빙 자동화**: 주문 완료 시 자동화 연동
- **야외 고객 유치와 인터랙티브 서비스**: 인터랙티브 서비스를 통한 고객 경험 향상

## System Architecture

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ UI                                                                                                           │
│                                                                                                              │
│  ┌────────────────────────────────────────┐   ┌────────────────────────────────────────────────────────────┐ │
│  │ Admin PC                               │   │ Voice Kiosk                                                │ │
│  │                                        │   │                                                            │ │
│  │        ┌────────────────────────┐      │   │        ┌────────────────────────────────────────┐          │ │
│  │        │        AdminGUI        │      │   │        │                OrderVUI                │          │ │
│  │        └────────────────────────┘      │   │        └────────────────────────────────────────┘          │ │
│  └────────────────────▲───────────────────┘   └───────────▲───────────────────────────▲────────────────────┘ │
└───────────────────────┼───────────────────────────────────┼───────────────────────────┼──────────────────────┘
                       TCP                                  │                           │ 
                        │                                  HTTP                        HTTP
┌───────────────────────┼───────────────────────────────────┼───────────────────────────┼──────────────────────┐
│ Service               │                                   │                           │                      │
│                       │                         ┌─────────┘                           │                      │
│  ┌────────────────────┼─────────────────────────┼───────────────┐  ┌──────────────────┼───────────────────┐  │
│  │ Operation Server   │                         │               │  │ AI Server        │                   │  │
│  │                    │                         ▼               │  │                  │                   │  │
│  │                    │         ┌────────────────────┐          │  │                  │                   │  │
│  │                    │         │     WebService     │          │  │                  │                   │  │
│  │                    │         └────────────────────┘          │  │                  │                   │  │
│  │                    │          ▲                              │  │                  │                   │  │
│  │                    │          │ TCP                          │  │                  │                   │  │
│  │                    ▼          ▼                              │  │                  ▼                   │  │
│  │  ┌──────────────────────────────┐               ┌─────────┐  │  │  ┌──────────────────────────────┐    │  │
│  │  │    MocaService               │◄─────TCP─────►│ MocaDB  │  │  │  │         VoiceService         │    │  │
│  │  └──────────────────────────────┘               └─────────┘  │  │  └──────────────────────────────┘    │  │
│  │         ▲                  ▲                                 │  │                                      │  │
│  └─────────┼──────────────────┼─────────────────────────────────┘  └──────────────────────────────────────┘  │
└────────────┼──────────────────┼──────────────────────────────────────────────────────────────────────────────┘
            ROS                ROS
             │                  │       
┌────────────┼──────────────────┼──────────────────────────────────────────────────────────────────────────────┐
│ Device     │                  └───────────────────────────────────────────┐                                  │
│            │                                                              │                                  │
│  ┌─────────┼──────────────────────┐     ┌─────────────────────────────────┼────────────────────────────────┐ │
│  │         ▼                      │     │                                 ▼                                │ │
│  │  ┌──────────────────────────┐  │     │  ┌────────────────────────────────────────────────────────────┐  │ │
│  │  │    DDoobyController      │  │     │  │                     DobyController                         │  │ │
│  │  └──────────────────────────┘  │     │  └──────────────┬───────────────────────────────┬─────────────┘  │ │
│  └────────────────────────────────┘     │                 │ ROS                           │ ROS            │ │
│                                         │                 ▼                               ▼                │ │
│                                         │  ┌──────────────────────────┐        ┌────────────────────────┐  │ │
│                                         │  │   MobilityController     │        │  SingleArmController   │  │ │
│                                         │  └──────────────────────────┘        └────────────────────────┘  │ │
│                                         └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
physical-ai-repo-3/
├── src/
│   ├── app/
│   │   ├── admin_gui/                        ── 운영자 GUI
│   │   ├── order_vui/                        ── 키오스크용 주문 웹앱
│   │   └── table_gui/                        ── 테이블 원격 주문 웹앱
│   ├── controller/
│   │   ├── controller_launch/                ── 컨트롤러 통합 launch
│   │   ├── controller_status_msgs/           ── 컨트롤러 상태 메시지 정의
│   │   ├── ddooby_controller/                ── 제조용 양팔 로봇 및 Gazebo 시뮬레이션
│   │   │   ├── assets/                       ── 제조 world, object, runtime asset
│   │   │   ├── launch/                       ── Gazebo, MoveIt, action server launch
│   │   │   └── openarm_vendor/               ── OpenArm Gazebo/MoveIt 의존 패키지
│   │   ├── doby_controller/                  ── 서빙/이동/호객 로봇 ROS 제어기
│   │   │   ├── scripts/                      ── 시뮬레이션 및 실행 스크립트
│   │   │   └── src/                          ── dobi_npc, Gazebo, navigation 패키지
│   │   ├── mobility_controller/              ── 모바일 베이스 제어기
│   │   └── single_arm_controller/            ── 단일 팔 제어기
│   └── service/
│   │   ├── moca_db/                          ── MySQL 초기화 및 스키마
│   │   ├── moca_service/                     ── 로봇 비즈니스 로직 및 통합 서비스
│   │   ├── web_service/                      ── REST + 정적 페이지 서빙
│   │   └── voice_service/                    ── ASR + LLM + TTS (GPU)
└── technical_research/                       ── 기술 조사 자료
```

## Setup

```bash
# 프로젝트 최상단 디렉터리에서 실행
PROJECT_ROOT="$(pwd)"

# [Step 1] doby_controller 빌드 및 실행
cd "$PROJECT_ROOT/src/controller/doby_controller"
source /opt/ros/jazzy/setup.bash
colcon build 
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
bash ./scripts/run_sim.sh

# [Step 2] ddooby_controller Gazebo 제조 world 빌드 및 실행
cd "$PROJECT_ROOT"
source /opt/ros/jazzy/setup.bash
colcon build \
  --base-paths src/controller/ddooby_controller src/controller/ddooby_controller/openarm_vendor \
  --symlink-install
source install/setup.bash
ros2 launch ddooby_controller manufacturing_world_gz.launch.py

# Gazebo, MoveGroup, RViz를 함께 띄우려면 아래 명령을 대신 실행
# ros2 launch ddooby_controller manufacturing_world_gz.launch.py with_rviz:=true

# [Step 3] operation (web_service, moca_db) 기동
cd "$PROJECT_ROOT/src/service"
docker compose -f docker-compose.operation.yml up -d

# [Step 4] moca_service 기동
cd "$PROJECT_ROOT/src/service"
bash ./run_moca_service_native.sh

# [Step 5] order_vui (키오스크 브라우저) 기동
chromium-browser --kiosk --ignore-certificate-errors https://localhost:8000/kiosk

# [Step 6] admin_gui 기동
cd "$PROJECT_ROOT/src/app/admin_gui"
./.venv/bin/python main.py
```

## Documentation

- [Installation](INSTALLATION.md): 설치, 배포, 접속 및 트러블슈팅 가이드
- [Developer Guide](DEVELOPER_GUIDE.md): 로컬 개발 가동, 재기동, 스키마 변경 및 운영 토폴로지 변경 가이드
