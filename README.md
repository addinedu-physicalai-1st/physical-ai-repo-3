# MOCA

음성 주문, 상품 제조·서빙·정리, 고객 안내와 호객까지 수행하는 자율주행 카페 로봇 통합 서비스 프로젝트입니다.

이 README는 음성 주문 흐름 (`web_service` + `voice_service`)을 처음부터 띄워 보는 방법을 안내합니다. 키오스크 앞에서 "주문할게요"라고 말해 메뉴를 담고, 스마트폰으로 QR 코드를 스캔하여 접속한 뒤 푸시-투-토크(PTT)로 주문하는 시나리오까지 따라할 수 있습니다.

## Core Features

- **음성 기반 주문 시스템**: 키오스크 wake word ("주문할게요") 및 폰 푸시-투-토크(Push-to-Talk) 지원
- **로봇 기반 상품 제조와 서빙 자동화**: 주문 완료 시 자동화 연동
- **야외 고객 유치와 인터랙티브 서비스**: 인터랙티브 서비스를 통한 고객 경험 향상

## System Architecture

MOCA 시스템은 서비스 운영을 담당하는 일반 PC(노트북)와 AI 모델 구동을 위한 GPU 머신(pai-server)의 하이브리드 아키텍처로 구성됩니다. 두 컴퓨터는 동일한 매장 내 Local Area Network(LAN) 상에 있어야 합니다.

```
노트북 (kiosk PC, CPU)                pai-server (GPU 머신)
┌──────────────────────────────┐     ┌────────────────────────────┐
│ docker-compose.operation.yml │     │ docker-compose.ai.yml      │
│   web_service   :8000 HTTPS  │←───→│   voice_service :8010 HTTPS│
│   moca_db       :3307        │     │     /asr  /llm  /tts       │
├──────────────────────────────┤     │   vision_service (별개)    │
│ (Native Host Process)        │     │                            │
│   moca_service  :9001        │     │                            │
│ Chromium kiosk mode          │     │                            │
└──────────────────────────────┘     └────────────────────────────┘
            ↑                                    ↑
            └─── 손님 폰 (Chrome) ───────────────┘
                  https://<노트북IP>:8000/table?no=N
```

### 접속 시나리오 및 흐름
- **키오스크**: `https://<노트북IP>:8000/kiosk` — Wake word "주문할게요"로 메뉴 화면 진입.
- **손님 스마트폰 (테이블)**: `https://<노트북IP>:8000/table?no=N` — QR 코드로 접속하여 원형 버튼을 누른 채로 발화하는 푸시-투-토크(PTT) 인터페이스 제공.
- **AI 서비스 (voice_service)**: GPU 자원을 필요로 하므로 별도의 GPU 머신(`pai-server`)에서 구동됩니다. 키오스크 및 스마트폰 브라우저는 획득한 음성 데이터를 `voice_service`로 직접 HTTPS fetch 요청을 보냅니다.
- **MOCA 서비스 (moca_service)**: 로봇의 ROS 제어 환경 등 호스트 측 리소스 연동을 위해 도커 외부(Native Host)의 독립된 백그라운드 프로세스로 구동됩니다.

## Directory Structure

```
physical-ai-repo-3/
├── src/
│   ├── service/                              ── 서버 측 서비스 모듈
│   │   ├── docker-compose.operation.yml      ── 노트북 운영 서비스 (web/db)
│   │   ├── docker-compose.ai.yml             ── pai-server AI 서비스 (voice)
│   │   ├── certs/                            ── mkcert 발급물 (git ignore)
│   │   ├── moca_db/                          ── MySQL 초기화 및 스키마
│   │   ├── moca_service/                     ── 로봇 비즈니스 로직 및 통합 서비스
│   │   ├── web_service/                      ── REST + 정적 페이지 서빙
│   │   └── voice_service/                    ── ASR + LLM + TTS (GPU)
│   ├── app/                                  ── 사용자 인터페이스
│   │   ├── order_vui/
│   │   │   ├── kiosk.html                    ── 키오스크 GUI + 음성
│   │   │   ├── audio/                        ── 안내음 wav
│   │   │   └── shared/                       ── voice.js, intent_handler.js 등 공용
│   │   ├── table_gui/
│   │   │   └── table.html                    ── 폰 페이지 (PTT)
│   │   └── admin_gui/                        ── 운영자 GUI
│   └── controller/                           ── 로봇 하드웨어 제어 모듈
│       └── doby_controller/                  ── Doby 로봇 하드웨어 ROS 제어기
├── scripts/                                  ── 진단/헬스 체크 스크립트
└── technical_research/                       ── 기술 조사 자료
```

## Installation

### 1. 사전 준비

#### 하드웨어 요구사항
- **노트북 1대**: Kiosk 구동 및 일반 서비스 운영. 매장 LAN에 연결.
- **pai-server 1대**: NVIDIA GPU 탑재 머신. Docker 및 NVIDIA Container Toolkit이 동작하는 매장 내 동일 LAN 환경.
- **네트워크**: 매장 Wi-Fi 라우터.

#### 소프트웨어 요구사항
- **노트북**: Docker, Docker Compose, mkcert (자체 CA 인증서 발급용), Chrome 또는 Chromium 브라우저.
- **pai-server**: Docker, Docker Compose, NVIDIA Container Toolkit (`nvidia-smi` 동작 상태).
- **손님 스마트폰**: 안드로이드 또는 iOS, Chrome 또는 Safari 브라우저 (매장 Wi-Fi 접속 필수).

---

### 2. 단계별 설치 및 기동 가이드

#### [Step 1] 코드 가져오기
```bash
git clone <이 레포 URL>
cd physical-ai-repo-3
```

#### [Step 2] mkcert로 자체 서명 SSL 인증서 발급 (노트북에서 실행)
모바일 브라우저에서 마이크 권한을 허용하려면 HTTPS(Secure Context) 연결이 필수적입니다. 로컬 개발 및 테스트 운영을 위해 `mkcert`를 사용하여 자체 서명 CA 인증서를 구성합니다.

1. **mkcert 설치 (Ubuntu/Debian 기준)**:
   ```bash
   sudo apt install libnss3-tools
   curl -L https://github.com/FiloSottile/mkcert/releases/latest/download/mkcert-v1.4.4-linux-amd64 -o mkcert
   chmod +x mkcert && sudo mv mkcert /usr/local/bin/
   ```
   *apt 패키지 설치가 어려울 경우 GitHub 릴리즈 바이너리를 직접 다운로드하여 적용합니다.*

2. **로컬 CA 등록 (최초 1회)**:
   ```bash
   mkcert -install
   ```

3. **인증서 발급 (노트북 IP, pai-server IP, localhost를 하나의 인증서로 묶음)**:
   ```bash
   mkdir -p src/service/certs
   cd src/service/certs
   mkcert -cert-file cert.pem -key-file key.pem \
     192.168.0.21 192.168.0.133 localhost 127.0.0.1
   cd -
   ```
   > [!IMPORTANT]
   > `192.168.0.21` 자리에는 노트북의 실제 IP, `192.168.0.133` 자리에는 `pai-server`의 실제 IP를 기입하십시오. (`ifconfig` 또는 `ip a`로 확인 가능)
   > 발급된 `src/service/certs/cert.pem`과 `key.pem`은 `.gitignore`에 등록되어 커밋되지 않으므로, 외부에 유출되지 않도록 주의해야 합니다.

#### [Step 3] pai-server 에 voice_service 배포
노트북에서 `pai-server`로 코드와 발급받은 인증서를 동기화합니다. (`pai-server`의 사용자 홈에 `~/voice_service_test` 디렉토리를 작업 영역으로 사용한다고 가정합니다.)

1. **노트북에서 동기화 실행**:
   ```bash
   rsync -avz src/service/voice_service/ \
     pai-server:~/voice_service_test/voice_service/

   rsync -avz src/service/docker-compose.ai.yml \
     pai-server:~/voice_service_test/docker-compose.ai.yml

   rsync -avz src/service/certs/ \
     pai-server:~/voice_service_test/certs/
   ```

2. **pai-server에 SSH 접속 후 빌드 및 기동**:
   ```bash
   ssh pai-server
   cd ~/voice_service_test
   docker compose -f docker-compose.ai.yml build voice_service
   docker compose -f docker-compose.ai.yml up -d voice_service
   ```
   > [!NOTE]
   > 첫 기동 시 HuggingFace로부터 Qwen3-ASR / Qwen2.5-3B / Qwen3-TTS 등의 AI 모델(약 9GB)을 다운로드하므로 네트워크 환경에 따라 10~30분 가량 소요될 수 있습니다. 이후 기동 시에는 `hf_cache` 볼륨에 캐싱된 모델을 로드하여 빠르게 작동합니다.

3. **AI 서비스 헬스 체크 (모델 로드 완료 여부 확인)**:
   ```bash
   curl -k https://192.168.0.133:8010/health
   ```
   응답 JSON 내 `asr_loaded`, `llm_loaded`, `tts_loaded` 속성이 모두 `true`가 되면 정상 작동 상태입니다.

#### [Step 4] 노트북에서 web_service / moca_db / moca_service 기동
1. **Docker 컨테이너 기동 (web_service, moca_db)**:
   ```bash
   cd src/service
   docker compose -f docker-compose.operation.yml up -d
   ```
   명령 실행 시 아래의 2개 운영 컨테이너가 기동됩니다:
   - `web_service`: 8000 (HTTPS 종단), 9004 (TCP, moca와 통신)
   - `moca_db`: 3307 (외부 DB 조회용)

2. **Native 호스트 서비스 기동 (moca_service)**:
   `moca_service`는 로봇의 ROS 제어 환경 등과의 연동을 위해 호스트에서 직접 네이티브 실행 스크립트로 기동해야 합니다.
   ```bash
   # src/service 디렉토리 내에서 실행
   ./run_moca_service_native.sh
   ```
   *(터미널을 닫은 상태에서도 백그라운드 유지하기 위해 `nohup ./run_moca_service_native.sh > moca_service.log 2>&1 &` 형태로 띄우는 것을 권장합니다.)*

3. **운영 서버 헬스 체크**:
   ```bash
   curl -k https://localhost:8000/health
   ```

#### [Step 5] 키오스크 접속 (노트북에서 실행)
노트북에서 크롬(Chrome) 브라우저를 열고 아래 URL에 접속합니다.
```
https://localhost:8000/kiosk
```
최초 접속 시 마이크 권한을 허용하고, 화면의 "마이크 시작" 버튼을 클릭하면 wake word 청취가 활성화됩니다. 손님이 "주문할게요"라고 말하면 메뉴 선택 화면으로 자동 진입합니다.

#### [Step 6] 손님 스마트폰 접속 절차
손님 스마트폰이 노트북과 동일한 매장 Wi-Fi에 연결되어 있어야 합니다.

1. **스마트폰에 로컬 CA 인증서(rootCA) 신뢰 설정 (기기별 최초 1회)**:
   - 노트북에서 mkcert rootCA 파일 경로를 확인합니다.
     ```bash
     mkcert -CAROOT
     # 예: /home/jin/.local/share/mkcert
     ```
   - 노트북에서 임시 웹 서버를 열어 rootCA를 모바일 기기에 공유합니다.
     ```bash
     cd $(mkcert -CAROOT)
     python3 -m http.server 8888
     ```
   - 스마트폰 브라우저로 `http://<노트북IP>:8888/rootCA.pem`에 접속하여 인증서 파일을 다운로드합니다.
   - 각 기기 OS별 인증서 설치 절차를 수행합니다.
     - **Android (One UI)**: 설정 → 보안 및 개인 정보 보호 → 자세히 → 자격 증명 저장소 → CA 인증서 설치 → 다운로드한 `rootCA.pem` 선택.
     - **iOS**: 설정 → 일반 → VPN 및 기기 관리 → 다운로드된 프로파일 설치. 이후 설정 → 일반 → 정보 → 인증서 신뢰 설정 에서 `mkcert` 관련 rootCA의 신뢰 토글을 활성화합니다.
   - 노트북에서 실행한 임시 파이썬 웹 서버(`Ctrl+C`)를 중지합니다.

2. **서비스 접속**:
   스마트폰 브라우저에서 아래 주소로 접속합니다.
   ```
   https://<노트북IP>:8000/table?no=1
   ```
   > [!NOTE]
   > `no=N` 파라미터는 테이블 번호입니다. 기본 시드 데이터 기준, 1번과 3번 테이블은 비어 있는 상태이고, 2번과 4번은 점유 상태이며, 5번 이상은 정의되지 않은 상태입니다.
   - 화면 하단의 큰 원형 마이크 버튼을 누르고 있는 동안(Push-to-Talk) 말을 한 뒤 손을 떼면 음성 인식이 이루어지며, 카트 추가 → 주문 확인 단계를 거쳐 최종 완료됩니다.

---

### 3. 설치 및 접속 문제 해결 (Troubleshooting)

- **발화 후 콘솔에 `Failed to fetch` 또는 `ERR_EMPTY_RESPONSE` 발생**:
  - 원인: 웹 서비스가 HTTPS 프로토콜로 종단되어 있으나 브라우저 페이지에 HTTP로 접속했거나, API 주소 경로가 불일치할 때 발생합니다.
  - 조치: 주소창의 URL이 `https://`로 시작하는지 확인하고, `kiosk.html`의 `API_BASE_URL` 변수가 `location.origin`으로 일치되어 있는지 확인하십시오.
- **스마트폰 접속 시 보안 경고가 뜨거나 마이크 권한 요청이 무반응인 현상**:
  - 원인: 폰에 로컬 CA 인증서가 정상적으로 설치/신뢰 등록되지 않은 상태입니다.
  - 조치: "Step 6"의 로컬 CA 설치 및 신뢰 설정을 다시 꼼꼼하게 수행해주십시오. 특히 iOS 기기는 프로파일 설치 외에도 **인증서 신뢰 설정**에서 토글 스위치를 수동으로 활성화해야 정상 동작합니다.
- **키오스크에서 "주문할게요" wake word가 전혀 동작하지 않는 문제**:
  - 조치: 주소창 좌측의 마이크 권한이 허용 상태인지 확인합니다. 개발자 도구 콘솔에 `[voice] mic acquired`와 `[voice] mic + KWS started` 로그가 잘 표시되는지 확인하십시오. 주변 환경 소음이 크거나 시스템 마이크 입력 볼륨이 너무 작을 경우 마이크 입력 게인을 확인하고 높여줍니다.
- **AI 서비스(voice_service) 응답이 반환되지 않고 멈추는 경우 (네트워크 지연 등)**:
  - 증상: 키오스크 개발자 도구 콘솔에 `Error: ASR timeout (8000ms)` 또는 `LLM timeout` 메시지가 발생합니다.
  - 조치: 타임아웃 발생 시 자동으로 follow-up listening 대기 상태로 복귀하며 "죄송해요, 다시 말씀해 주세요" 라는 TTS 안내가 이루어집니다. 컨테이너 상태나 네트워크 연결을 점검하십시오.
- **키오스크에서 30초 이상 무발화 상태임에도 대기(Standby) 모드로 복귀하지 않는 문제**:
  - 원인: 주변의 백그라운드 소음이 VAD 임계값을 초과하여 발화가 계속 지속되는 것으로 잘못 해석되는 현상입니다.
  - 조치: `src/app/order_vui/shared/voice.js` 파일 내 `positiveSpeechThreshold` (기본값: 0.7) 및 `minSpeechFrames` (기본값: 8) 값을 매장/환경 소음 수준에 맞게 튜닝하십시오.

## Developer Guide

### 1. 단일 로컬 컴퓨터 개발 가동용 명령어 모음 (순차 실행)

```bash
# [Step 1] doby_controller 빌드 및 실행
cd /home/robo/projects/final_project/src/controller/doby_controller
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
export ROS_DOMAIN_ID=99
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch dobi_npc_bringup dobi_npc_bringup.launch.py

# [Step 2] operation (web_service, moca_db) 기동
cd /home/robo/projects/final_project/src/service
docker compose -f docker-compose.operation.yml up -d

# [Step 3] moca_service 기동
cd /home/robo/projects/final_project/src/service
./run_moca_service_native.sh

# [Step 4] order_vui (키오스크 브라우저) 기동
chromium-browser --kiosk --ignore-certificate-errors https://localhost:8000/kiosk

# [Step 5] admin_gui 기동
cd /home/robo/projects/final_project/src/app/admin_gui
./.venv/bin/python main.py
```

---

### 2. 코드 변경 사항 실시간 반영 및 재기동 가이드

- **정적 웹 자원 (`src/app/order_vui/**`, `src/app/table_gui/**`)**:
  - `web_service` 컨테이너에 호스트 볼륨으로 실시간 바인딩 마운트(Read-Only)되어 있습니다. 코드 수정 후 브라우저에서 **강제 새로고침(Ctrl + F5)**만 수행하면 변경 내용이 즉시 반영됩니다.
- **노트북 Python 웹 서비스 코드 (`src/service/web_service/app/**`)**:
  - 수정 사항을 반영하기 위해 아래 명령으로 서비스를 강제 재기동해야 합니다.
    ```bash
    docker compose -f docker-compose.operation.yml up -d --force-recreate web_service
    ```
- **pai-server AI 서비스 코드 (`src/service/voice_service/app/**`)**:
  - 코드 변경 사항을 `pai-server`에 동기화한 뒤 컨테이너를 재빌드하고 재기동해야 합니다.
    ```bash
    # [1] 노트북에서 pai-server로 코드 동기화
    rsync -avz src/service/voice_service/app/ \
      pai-server:~/voice_service_test/voice_service/app/

    # [2] pai-server SSH 터미널에서 재빌드 및 강제 기동
    docker compose -f docker-compose.ai.yml build voice_service
    docker compose -f docker-compose.ai.yml up -d --force-recreate voice_service
    ```

---

### 3. 데이터베이스 및 스키마 변경 이슈 해결

코드 병합(Merge)이나 깃 풀(Pull) 이후 테이블 정의가 추가되거나 변경되었을 때, Native로 동작하는 `moca_service` 가 정상 동작하지 않거나 DB 통신 에러(`ProgrammingError: Table 'business.xxx' doesn't exist`)가 발생할 수 있습니다.

#### 발생 원인
1. **Docker 빌드 캐싱**: `web_service`는 빌드 시점에 호스트 코드를 컨테이너 내부로 직접 `COPY`하므로, 소스 코드 변경 시 이미지 재빌드(`--build`) 없이 기동하면 구버전 빌드가 적용되어 오류가 지속될 수 있습니다.
2. **MySQL 초기화 메커니즘**: `moca_db`는 영구 볼륨(`service_moca_db_data`)을 사용합니다. MySQL의 초기화 스크립트(`/docker-entrypoint-initdb.d/init.sql`)는 **최초 기동 시에 데이터 디렉토리가 비어있을 때만 실행**되므로, 데이터가 이미 있다면 스키마 변경이 자동으로 반영되지 않습니다.

#### 문제 해결 방법 (A 또는 B 방법 중 택일)

- **방법 A: 데이터베이스 전체 초기화 (데이터 유실이 상관없는 개발 환경용)**
  기존 스토어/주문 데이터를 모두 삭제하고 초기 스키마부터 완전히 새로 설치합니다.
  ```bash
  cd src/service
  # 1. 실행 중인 Native moca_service 프로세스 중지
  pkill -f "python -m app.main" || true
  
  # 2. 운영 컨테이너 중지 및 기존 DB 데이터 볼륨 삭제
  docker compose -f docker-compose.operation.yml down
  docker volume rm service_moca_db_data
  
  # 3. DB 및 Web 서비스 컨테이너 재생성 및 실행
  docker compose -f docker-compose.operation.yml up -d moca_db web_service
  
  # 4. Native moca_service 재기동
  ./run_moca_service_native.sh
  ```
  *(참고: 볼륨 이름은 프로젝트 디렉토리명에 따라 다를 수 있으므로 `docker volume ls | grep moca_db_data`로 확인 후 제거하십시오.)*

- **방법 B: 기존 데이터 유지 상태에서 `init.sql` 멱등적 재적용**
  기존 주문 기록이나 시드 데이터를 유지하면서 변경된 테이블만 추가합니다. (MOCA의 `init.sql`은 `CREATE TABLE IF NOT EXISTS`, `INSERT IGNORE` / `ON DUPLICATE KEY UPDATE` 패턴으로 작성되어 있어 안전하게 수동 재처리가 가능합니다.)
  ```bash
  cd src/service
  # 1. 가동 중인 DB 내부에 직접 init.sql 적용
  docker exec -i moca_db mysql -u business_user -pbusiness_password business \
    < src/service/moca_db/init.sql
  
  # 2. 실행 중인 Native moca_service 프로세스 재기동
  pkill -f "python -m app.main" || true
  ./run_moca_service_native.sh
  ```

#### 스키마 적용 여부 검증
```bash
# DB 내 테이블 목록 확인
docker exec moca_db mysql -u business_user -pbusiness_password \
  -e "USE business; SHOW TABLES;"

# MOCA TCP 통신 테스트 스크립트 실행
python3 scripts/test_moca_tcp_client.py all
```
`SHOW TABLES` 결과로 `allergy_category, order_item, orders, product, product_allergy, product_option_group, service_metadata, store_table` 등이 모두 조회되고, TCP 진단 스크립트가 정상적으로 데이터 응답을 출력하면 성공입니다.
*(참고: `moca_service`는 데이터베이스 연동 실패 시 최대 30회 재시도 후 프로세스가 자동 종료되므로, 시작 후 갑자기 소멸한다면 터미널 로그 및 에러 메시지를 점검해 보십시오.)*

---

### 4. 메뉴 / 별명 / 알레르기 정보 수정 (단일 진실 원칙)

MOCA의 모든 메뉴 정보는 **`src/service/web_service/app/data/seed.py`** 파일에서 통합 관리됩니다. (Single Source of Truth)

- **메뉴 변경 시**: `seed.py` 파일 내 `MenuItem` 객체의 `name`, `aliases` (별칭 목록), `price`, `emoji`, 알레르기 플래그 등을 직접 수정합니다.
- **자동 전파 경로**: `seed.py` 수정 후 서버가 재구동되면 `/api/menu` API의 응답이 갱신되며, 브라우저 클라이언트의 글로벌 MENU 정보, ASR 컨텍스트(음성 매핑용 단어 사전), LLM 시스템 프롬프트 내부의 `현재 메뉴 [별명]` 리스트까지 자동으로 반영 및 전파됩니다.
- **ASR 예외 처리**:
  - 만약 특정 별칭에 대해 음성 인식이 유독 취약한 경우, `src/service/voice_service/app/llm/prompts.py` 내의 `_FEW_SHOTS` 리스트에 실제 고객 발화에 대응하는 Few-Shot 예시 데이터를 1~2개 추가해 줍니다.
  - ASR 응답이 MOCA 시스템 컨텍스트의 템플릿(예: `"메뉴: 아메리카노 ..."` 같은 프롬프트 echo 형태)을 그대로 흉내 내어 반환하는 예외의 경우, LLM 시스템 프롬프트에 내장된 'ASR context echo 차단' 규칙에 의해 `unknown` 처리되며, 사용자 화면에는 장바구니 오작동을 차단하고 "다시 말씀해 주세요" 라는 안내를 보냅니다.

---

### 5. 운영 환경 토폴로지 변경 가이드 (IP 변경 시)

네트워크 망 변경 등으로 서버들의 IP 주소가 변경될 경우 아래 절차를 차례로 진행합니다.

1. **SSL 인증서 재발급**:
   - 변경된 노트북 및 `pai-server` IP를 반영하여 `mkcert` 명령어를 다시 실행해 인증서를 갱신합니다. (Installation 가이드 Step 2 참고)
2. **클라이언트 주소 갱신**:
   - `src/app/order_vui/kiosk.html` 및 `src/app/table_gui/table.html` 파일 상단에 정의된 `window.VOICE_SERVICE_URL` 변수의 IP 주소를 새로 변경된 `pai-server` IP로 수정합니다.
3. **배포 및 재실행**:
   - `docker-compose.ai.yml`과 `docker-compose.operation.yml` 구성 설정은 그대로 유지한 채 서비스를 각각 재기동합니다.
