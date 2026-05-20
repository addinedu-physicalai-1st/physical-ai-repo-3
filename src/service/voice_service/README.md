# voice_service

음성 주문 추론 서버. `/asr/transcribe`, `/llm/intent`, `/tts/speak` 엔드포인트를 제공한다.

## 엔드포인트

| 메서드 | 경로 | 입력 | 출력 |
|---|---|---|---|
| GET | `/health` | — | `{status, asr_loaded, llm_loaded, tts_loaded, gpu, service}` |
| POST | `/asr/transcribe` | multipart `file` (wav) + form `context` (옵션) | `{text, latency_ms, samples, sample_rate}` |
| POST | `/llm/intent` | JSON `{user_text, current_screen, cart, menu}` | intent JSON |
| POST | `/tts/speak` | (Phase 5) | — |

LLM intent 응답:
```jsonc
{
  "intent": "add_menu | remove_menu | set_option | confirm_order | back | checkout | select_payment | allergy_confirm | cancel_all | unknown",
  "items": [{"menu_name": "아메리카노", "qty": 2, "options": {"shot": "extra"}}],
  "payment_method": "card | apple_pay | samsung_pay | null",
  "response_text": "...",
  "latency_ms": 123.4,
  "raw": "..."
}
```

## Phase 별 작업

- Phase 0: `/health` 만 동작
- Phase 2 (현재): `/asr/transcribe` (Qwen3-ASR-0.6B), `/llm/intent` (Qwen2.5-3B-Instruct)
- Phase 5: `/tts/speak`

## 기동

GPU 머신 (pai-server) 에서 docker-compose 로 기동한다.

```bash
cd src/service
docker compose -f docker-compose.ai.yml build voice_service
docker compose -f docker-compose.ai.yml up -d voice_service
docker compose -f docker-compose.ai.yml logs -f voice_service
```

첫 기동 시 HuggingFace 에서 모델 다운로드 (~6GB: Qwen3-ASR-0.6B + Qwen2.5-3B-Instruct). `hf_cache` named volume 에 영속화되어 재기동 시 재사용된다.

빌드 시 torch + cuda wheel (~1GB) 다운로드. nvidia/cuda 베이스 이미지 대신 `python:3.12-slim` + torch wheel 만으로 GPU 사용 (PoC 와 동일 환경).

## 환경변수

| 이름 | 기본값 | 용도 |
|---|---|---|
| `VOICE_SERVICE_NAME` | `voice_service` | 서비스 식별자 |
| `VOICE_SERVICE_HTTP_HOST` | `0.0.0.0` | 바인드 호스트 |
| `VOICE_SERVICE_HTTP_PORT` | `8010` | HTTP 포트 |
| `HF_HOME` | `/root/.cache/huggingface` | HF 캐시 (compose 에서 자동 설정) |
| `HUGGINGFACE_HUB_CACHE` | 위와 동일 | 동일 |

## 검증 (curl)

```bash
# 1) 상태 확인 — 모델 로드 완료 시 asr_loaded/llm_loaded 가 true
curl -s http://localhost:8010/health | jq

# 2) ASR — 16kHz wav 업로드
curl -s -F "file=@sample.wav" -F "context=카페 메뉴 주문" \
     http://localhost:8010/asr/transcribe | jq

# 3) LLM intent
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"user_text":"아메리카노 두 잔 주세요","menu":[{"name":"아메리카노"},{"name":"카페라떼"}]}' \
     http://localhost:8010/llm/intent | jq
```
