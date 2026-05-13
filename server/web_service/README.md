# web_service

카페 키오스크 / 테이블 QR 주문 HTTP 백엔드와 BusinessService 연동용 TCP API.

## 셋업 (최초 1회)

```bash
cd server/web_service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 실행

```bash
cd server/web_service
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- 키오스크: http://localhost:8000/kiosk
- 테이블 QR (테이블 3번 예시): http://localhost:8000/table?table=3
- TCP API: `WEB_SERVICE_TCP_PORT` 환경변수 기본값 `9004`

## 테스트

```bash
cd server/web_service
source .venv/bin/activate
pytest
```

## API

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/menu` | 메뉴 목록 |
| GET | `/api/allergy` | 알러지 정보 |
| GET | `/api/tables` | 테이블 점유 상태 |
| POST | `/api/orders` | 주문 생성 |
| GET | `/api/orders/{id}` | 주문 조회 |

## TCP API

JSON lines 형식으로 요청/응답합니다.

| type | 설명 |
|---|---|
| `health` | 서비스 health 응답 |
| `status` | HTTP/TCP listener와 dependency 상태 응답 |
