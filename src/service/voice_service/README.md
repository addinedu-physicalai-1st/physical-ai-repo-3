# voice_service

음성 주문 추론 서버. `/asr/transcribe`, `/llm/intent`, `/tts/speak` 엔드포인트를 제공한다. Phase 0 단계에서는 `/health` 만 노출되어 배선 검증용으로 사용된다.

## 기동

### 도커 (권장)
`docker-compose.ai.yml` 의 `voice_service` 블록으로 기동:

```bash
cd src/service
docker compose -f docker-compose.ai.yml up -d voice_service
```

### 직접 실행 (개발)
```bash
cd src/service/voice_service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app
```

## 환경변수

| 이름 | 기본값 | 용도 |
|---|---|---|
| `VOICE_SERVICE_NAME` | `voice_service` | 서비스 식별자 |
| `VOICE_SERVICE_HTTP_HOST` | `0.0.0.0` | 바인드 호스트 |
| `VOICE_SERVICE_HTTP_PORT` | `8010` | HTTP 포트 |

## Phase 별 작업

- Phase 0 (현재): `/health` 만 동작
- Phase 1: 미사용 (브라우저 측 KWS 작업)
- Phase 2: `/asr/transcribe`, `/llm/intent` 추가 (GPU 모델 로드)
- Phase 5: `/tts/speak` 추가
