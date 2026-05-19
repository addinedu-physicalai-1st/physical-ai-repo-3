# MOCA — 음성 + 자율주행 카페 로봇 통합 서비스

음성 주문, 상품 제조·서빙·정리, 고객 안내와 호객까지 수행하는 자율주행 카페 로봇 통합 서비스 프로젝트입니다.

이 README 는 음성 주문 흐름 (`web_service` + `voice_service`) 을 처음부터 띄워 보는 방법을 안내합니다. 키오스크 앞에서 "주문할게요" 라고 말해 메뉴를 담고, 폰에서 QR 로 들어와 푸시-투-토크로 주문하는 시나리오까지 따라할 수 있습니다.

## Core Features

- 음성 기반 주문 시스템 (키오스크 wake word + 폰 푸시-투-토크)
- 로봇 기반 상품 제조와 서빙 자동화
- 야외 고객 유치와 인터랙티브 서비스

## 시스템 구성 (음성 주문 흐름)

두 대의 컴퓨터가 필요합니다. 같은 매장 LAN 안에 둡니다.

```
노트북 (kiosk PC, CPU)                pai-server (GPU 머신)
┌──────────────────────────────┐     ┌────────────────────────────┐
│ docker-compose.operation.yml │     │ docker-compose.ai.yml      │
│   web_service   :8000 HTTPS  │←───→│   voice_service :8010 HTTPS│
│   moca_service  :9001        │     │     /asr  /llm  /tts       │
│   moca_db       :3307        │     │   vision_service (별개)    │
│ Chromium kiosk mode          │     │                            │
└──────────────────────────────┘     └────────────────────────────┘
            ↑                                    ↑
            └─── 손님 폰 (Chrome) ───────────────┘
                  https://<노트북IP>:8000/table?no=N
```

손님이 보는 페이지는 두 종류입니다.

- 키오스크: `https://<노트북IP>:8000/kiosk` — wake word "주문할게요" 로 시작.
- 폰 (테이블): `https://<노트북IP>:8000/table?no=N` — QR 로 진입, 푸시-투-토크 버튼.

`voice_service` 는 GPU 가 필요해 별도 머신 (pai-server) 에 둡니다. 키오스크/폰 브라우저가 음성 데이터를 직접 voice_service 에 fetch 합니다.

## 사전 준비

### 하드웨어

- 노트북 1대 (kiosk + 일반 서비스 운영). 매장 LAN.
- pai-server 1대. NVIDIA GPU 와 Docker 의 NVIDIA Container Toolkit. 같은 LAN.
- 매장 Wi-Fi 라우터.

### 소프트웨어

노트북 쪽:

- Docker / Docker Compose
- mkcert (자체 CA 인증서 발급)
- Chrome 또는 Chromium

pai-server 쪽:

- Docker / Docker Compose
- NVIDIA Container Toolkit (`nvidia-smi` 가 호스트에서 동작하는 상태)

폰 쪽:

- 안드로이드 또는 iOS, Chrome 또는 Safari
- 매장 Wi-Fi 에 접속 가능

## 빠른 시작 (요약)

처음 본 사람도 따라할 수 있는 최소 절차입니다. 각 단계 상세 설명은 다음 섹션에 있습니다.

```
1. mkcert 로 노트북에서 self-signed CA 와 인증서 발급
2. 인증서 파일을 src/service/certs/ 에 두기
3. pai-server 에 voice_service 폴더 동기화 + 인증서 동기화
4. pai-server 에서 docker compose -f docker-compose.ai.yml up -d
5. 노트북에서 docker compose -f docker-compose.operation.yml up -d
6. Chrome 으로 https://localhost:8000/kiosk 접속
```

## 단계별 안내

### 1. 코드 가져오기

```
git clone <이 레포 URL>
cd physical-ai-repo-3
```

### 2. mkcert 로 인증서 발급 (노트북에서)

손님 폰의 브라우저는 마이크 권한을 HTTPS (secure context) 에서만 허용합니다. 운영 단계 전까지는 mkcert 로 발급한 self-signed CA 인증서로 HTTPS 종단을 합니다.

mkcert 설치 (Ubuntu/Debian):

```
sudo apt install libnss3-tools
curl -L https://github.com/FiloSottile/mkcert/releases/latest/download/mkcert-v1.4.4-linux-amd64 -o mkcert
chmod +x mkcert && sudo mv mkcert /usr/local/bin/
```

apt 패키지가 잘 안 들어가면 위처럼 GitHub 릴리즈 바이너리 직접 받습니다.

로컬 CA 등록 (한 번만):

```
mkcert -install
```

인증서 발급 (노트북 IP + pai-server IP + localhost 를 한 인증서에 묶음):

```
mkdir -p src/service/certs
cd src/service/certs
mkcert -cert-file cert.pem -key-file key.pem \
  192.168.0.21 192.168.0.133 localhost 127.0.0.1
cd -
```

`192.168.0.21` 자리에 노트북 IP, `192.168.0.133` 자리에 pai-server IP 를 넣습니다. `ifconfig` 또는 `ip a` 로 확인 가능.

발급된 `src/service/certs/cert.pem` 과 `key.pem` 은 `.gitignore` 에 등록되어 commit 되지 않습니다. 절대 외부로 유출하지 마세요.

손님 폰에 rootCA 신뢰 등록도 필요합니다 (아래 "폰 접속 절차" 참고).

### 3. pai-server 에 voice_service 배포

노트북에서 pai-server 로 코드와 인증서를 동기화합니다. pai-server 의 사용자 홈에 `~/voice_service_test` 라는 작업 디렉토리를 둔다고 가정합니다.

```
# 노트북에서
rsync -avz src/service/voice_service/ \
  pai-server:~/voice_service_test/voice_service/

rsync -avz src/service/docker-compose.ai.yml \
  pai-server:~/voice_service_test/docker-compose.ai.yml

# 인증서도 같이
rsync -avz src/service/certs/ \
  pai-server:~/voice_service_test/certs/
```

pai-server 에 ssh 접속 후 빌드 + 기동:

```
ssh pai-server
cd ~/voice_service_test
docker compose -f docker-compose.ai.yml build voice_service
docker compose -f docker-compose.ai.yml up -d voice_service
```

첫 기동 시 Qwen3-ASR / Qwen2.5-3B / Qwen3-TTS 모델을 HuggingFace 에서 약 9GB 다운로드합니다 (10~30 분 소요). 두 번째 기동부터는 `hf_cache` 볼륨에 캐시되어 빨라집니다.

헬스 체크 (모델 로드 완료 확인):

```
curl -k https://192.168.0.133:8010/health
```

응답에 `asr_loaded`, `llm_loaded`, `tts_loaded` 가 모두 `true` 면 준비 완료.

### 4. 노트북에서 web_service / moca_service / moca_db 기동

```
cd src/service
docker compose -f docker-compose.operation.yml up -d
```

세 컨테이너가 동시에 뜹니다.

- `web_service` 8000 HTTPS, 9004 TCP (moca 와 통신)
- `moca_service` 9001
- `moca_db` 3307 (호스트 노출용)

헬스 체크:

```
curl -k https://localhost:8000/health
```

### 5. 키오스크 접속 (노트북에서)

Chrome 으로 다음 URL 접속:

```
https://localhost:8000/kiosk
```

첫 접속에서 마이크 권한 허용. "마이크 시작" 버튼을 누르면 wake word 청취 시작. 손님이 "주문할게요" 라고 말하면 메뉴 화면으로 진입합니다.

### 6. 폰 접속 절차

같은 매장 Wi-Fi 에 폰을 연결합니다.

rootCA 설치 (폰마다 한 번만):

1. 노트북에서 mkcert rootCA 파일 경로 확인.

```
mkcert -CAROOT
# 예: /home/jin/.local/share/mkcert
```

2. 노트북에서 임시 HTTP 서버로 rootCA 파일을 공유.

```
cd $(mkcert -CAROOT)
python3 -m http.server 8888
```

3. 폰 Chrome 으로 `http://<노트북IP>:8888/rootCA.pem` 접속 → 파일 다운로드.

4. 폰 설정에서 CA 인증서로 설치.

- 안드로이드 One UI: 설정 → 보안 및 개인 정보 보호 → 자세히 → 자격 증명 저장소 → CA 인증서 설치 → 다운로드 폴더의 파일 선택.
- iOS: 설정 → 일반 → VPN 및 기기 관리 → 다운로드된 프로파일 → 설치. 그 다음 설정 → 일반 → 정보 → 인증서 신뢰 설정 에서 rootCA 신뢰 켜기.

5. 노트북에서 임시 HTTP 서버 (`python3 -m http.server 8888`) 중지.

6. 폰 Chrome 으로 접속.

```
https://<노트북IP>:8000/table?no=1
```

`no=N` 의 N 은 테이블 번호. 기본 시드에서는 1 과 3 만 비어 있고 2, 4 는 점유 상태, 5 이상은 정의되지 않은 상태입니다.

화면 하단의 큰 원형 버튼을 누른 채로 발화 → 떼면 음성 인식 → 카트 추가 → "주문 확인" 으로 진행 → 카운터 안내 화면으로 마무리.

## 자주 보이는 문제

발화 했는데 콘솔에 `Failed to fetch` 또는 `ERR_EMPTY_RESPONSE`

- 페이지가 HTTP 인데 web_service 가 HTTPS 종단 상태일 때 발생.
- 페이지 URL 이 `https://` 로 시작하는지 확인.
- `kiosk.html` 의 `API_BASE_URL` 이 `location.origin` 으로 설정되어 있어야 합니다 (Phase 7 fix 완료).

폰에서 자물쇠 깨짐 또는 마이크 권한 요청이 안 뜸

- 폰에 rootCA 가 신뢰 등록되지 않은 상태.
- 위의 "폰 접속 절차" 의 rootCA 설치 단계를 다시 수행.
- iOS 의 경우 "인증서 신뢰 설정" 화면에서 rootCA 토글을 켰는지 재확인.

키오스크에서 "주문할게요" 가 인식 안 됨

- 마이크 권한이 허용되어 있는지 (주소창 왼쪽 자물쇠 → 사이트 권한).
- 콘솔에 `[voice] mic acquired` 와 `[voice] mic + KWS started` 로그가 보이는지.
- 마이크 입력 음량이 너무 작을 수 있음. 시스템 사운드 설정에서 입력 게인 확인.

ASR 응답이 우리 context 를 그대로 echo (`"메뉴: 아메리카노 ..."` 같은 텍스트)

- Phase 7 fix 로 LLM 시스템 프롬프트의 "ASR context echo 차단" 규칙이 unknown 으로 처리.
- 손님 화면에는 "다시 말씀해 주세요" TTS 안내. 카트 자동 추가 없음.

voice_service 가 응답 못 보냄 (network 단절, 컨테이너 hang 등)

- 키오스크 콘솔에 `Error: ASR timeout (8000ms)` 또는 `LLM timeout` 메시지.
- 자동으로 follow-up listening 으로 복귀.
- "죄송해요, 다시 말씀해 주세요" TTS 안내 (TTS 도 실패하면 무음).

키오스크에서 30 초 침묵 후에도 standby 복귀 안 됨

- 환경 잡음이 VAD 임계값을 넘어 발화로 잡히는 경우 무발화 카운트가 갱신될 수 있음 (Phase 7 의 잡음 robust 로직으로 anchor 는 갱신 안 되지만, VAD 임계값 자체가 환경마다 조정 필요).
- `voice.js` 의 `positiveSpeechThreshold` (현재 0.7), `minSpeechFrames` (현재 8) 를 환경에 맞춰 조정.

## 디렉토리 구조

```
physical-ai-repo-3/
├── src/
│   ├── service/                              ── 도커 컨테이너 (서버 측)
│   │   ├── docker-compose.operation.yml      ── 노트북. web/moca/db
│   │   ├── docker-compose.ai.yml             ── pai-server. voice/vision
│   │   ├── certs/                            ── mkcert 발급물 (git ignore)
│   │   ├── moca_db/   moca_service/          ── 기존
│   │   ├── web_service/                      ── REST + 정적 페이지 서빙
│   │   └── voice_service/                    ── ASR + LLM + TTS (GPU)
│   └── app/                                  ── 사용자 인터페이스
│       ├── order_vui/
│       │   ├── kiosk.html                    ── 키오스크 GUI + 음성
│       │   ├── audio/                        ── 안내음 wav
│       │   └── shared/                       ── voice.js, intent_handler.js 등 공용
│       ├── table_gui/
│       │   └── table.html                    ── 폰 페이지 (PTT)
│       └── admin_gui/                        ── 운영자 GUI
├── scripts/                                  ── 진단/헬스 체크 스크립트
└── technical_research/                       ── 기술 조사 자료
```

## 개발자용 정보

코드 수정 후 재기동 가이드:

- `src/app/order_vui/**` 또는 `src/app/table_gui/**` 정적 파일은 web_service 컨테이너에 read-only 마운트되어 있어 브라우저 새로고침 (Ctrl+F5) 만으로 반영.
- `src/service/web_service/app/**` Python 코드는 web_service 컨테이너 재기동 필요.
  ```
  docker compose -f docker-compose.operation.yml up -d --force-recreate web_service
  ```
- `src/service/voice_service/app/**` Python 코드는 pai-server 에 동기화 후 voice_service 빌드 + 재기동.
  ```
  rsync -avz src/service/voice_service/app/ \
    pai-server:~/voice_service_test/voice_service/app/
  # pai-server 에서
  docker compose -f docker-compose.ai.yml build voice_service
  docker compose -f docker-compose.ai.yml up -d --force-recreate voice_service
  ```

메뉴 / 별명 / 알러지 변경 시 수정 위치 (단일 진실: seed.py):

- `src/service/web_service/app/data/seed.py` 에서 MenuItem 의 `name`, `aliases`, `price`, `emoji`, 옵션 플래그를 수정.
- `/api/menu` 응답이 갱신되고, 키오스크 / 폰의 MENU 전역, ASR context (메뉴명 + 별명), LLM 시스템 프롬프트의 "현재 메뉴 [별명]" 블록까지 자동 전파.
- 별명 인식이 약한 경우만 추가로 `src/service/voice_service/app/llm/prompts.py` 의 `_FEW_SHOTS` 에 학습 예시 한두 줄 추가.

운영 토폴로지 변경 시 (서버 IP 가 바뀔 때):

- mkcert 인증서 재발급 (SAN 갱신).
- pai-server 의 `docker-compose.ai.yml` 그대로.
- 노트북의 `docker-compose.operation.yml` 그대로.
- `src/app/order_vui/kiosk.html` 과 `src/app/table_gui/table.html` 의 `window.VOICE_SERVICE_URL` 에 새 pai-server IP 를 반영.
