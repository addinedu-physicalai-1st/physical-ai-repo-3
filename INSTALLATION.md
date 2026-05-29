# Installation

## 1. 사전 준비

### 하드웨어 요구사항
- **노트북 1대**: Kiosk 구동 및 일반 서비스 운영. 매장 LAN에 연결.
- **pai-server 1대**: NVIDIA GPU 탑재 머신. Docker 및 NVIDIA Container Toolkit이 동작하는 매장 내 동일 LAN 환경.
- **네트워크**: 매장 Wi-Fi 라우터.

### 소프트웨어 요구사항
- **노트북**: Docker, Docker Compose, mkcert (자체 CA 인증서 발급용), Chrome 또는 Chromium 브라우저.
- **pai-server**: Docker, Docker Compose, NVIDIA Container Toolkit (`nvidia-smi` 동작 상태).
- **손님 스마트폰**: 안드로이드 또는 iOS, Chrome 또는 Safari 브라우저 (매장 Wi-Fi 접속 필수).

---

## 2. 단계별 설치 및 기동 가이드

### [Step 1] 코드 가져오기
```bash
git clone <이 레포 URL>
cd physical-ai-repo-3
```

### [Step 2] mkcert로 자체 서명 SSL 인증서 발급 (노트북에서 실행)
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

### [Step 3] pai-server 에 voice_service 배포
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

### [Step 4] 노트북에서 web_service / moca_db / moca_service 기동
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

### [Step 5] 키오스크 접속 (노트북에서 실행)
노트북에서 크롬(Chrome) 브라우저를 열고 아래 URL에 접속합니다.
```
https://localhost:8000/kiosk
```
최초 접속 시 마이크 권한을 허용하고, 화면의 "마이크 시작" 버튼을 클릭하면 wake word 청취가 활성화됩니다. 손님이 "주문할게요"라고 말하면 메뉴 선택 화면으로 자동 진입합니다.

### [Step 6] 손님 스마트폰 접속 절차
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

## 3. 설치 및 접속 문제 해결 (Troubleshooting)

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
