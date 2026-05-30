# Developer Guide

## 코드 변경 사항 실시간 반영 및 재기동 가이드

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

## 데이터베이스 및 스키마 변경 이슈 해결

코드 병합(Merge)이나 깃 풀(Pull) 이후 테이블 정의가 추가되거나 변경되었을 때, Native로 동작하는 `moca_service` 가 정상 동작하지 않거나 DB 통신 에러(`ProgrammingError: Table 'business.xxx' doesn't exist`)가 발생할 수 있습니다.

### 발생 원인
1. **Docker 빌드 캐싱**: `web_service`는 빌드 시점에 호스트 코드를 컨테이너 내부로 직접 `COPY`하므로, 소스 코드 변경 시 이미지 재빌드(`--build`) 없이 기동하면 구버전 빌드가 적용되어 오류가 지속될 수 있습니다.
2. **MySQL 초기화 메커니즘**: `moca_db`는 영구 볼륨(`service_moca_db_data`)을 사용합니다. MySQL의 초기화 스크립트(`/docker-entrypoint-initdb.d/init.sql`)는 **최초 기동 시에 데이터 디렉토리가 비어있을 때만 실행**되므로, 데이터가 이미 있다면 스키마 변경이 자동으로 반영되지 않습니다.

### 문제 해결 방법 (A 또는 B 방법 중 택일)

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

### 스키마 적용 여부 검증
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

## 4. 메뉴 / 별명 / 알레르기 정보 수정 (단일 진실 원칙)

MOCA의 모든 메뉴 정보는 **`src/service/web_service/app/data/seed.py`** 파일에서 통합 관리됩니다. (Single Source of Truth)

- **메뉴 변경 시**: `seed.py` 파일 내 `MenuItem` 객체의 `name`, `aliases` (별칭 목록), `price`, `emoji`, 알레르기 플래그 등을 직접 수정합니다.
- **자동 전파 경로**: `seed.py` 수정 후 서버가 재구동되면 `/api/menu` API의 응답이 갱신되며, 브라우저 클라이언트의 글로벌 MENU 정보, ASR 컨텍스트(음성 매핑용 단어 사전), LLM 시스템 프롬프트 내부의 `현재 메뉴 [별명]` 리스트까지 자동으로 반영 및 전파됩니다.
- **ASR 예외 처리**:
  - 만약 특정 별칭에 대해 음성 인식이 유독 취약한 경우, `src/service/voice_service/app/llm/prompts.py` 내의 `_FEW_SHOTS` 리스트에 실제 고객 발화에 대응하는 Few-Shot 예시 데이터를 1~2개 추가해 줍니다.
  - ASR 응답이 MOCA 시스템 컨텍스트의 템플릿(예: `"메뉴: 아메리카노 ..."` 같은 프롬프트 echo 형태)을 그대로 흉내 내어 반환하는 예외의 경우, LLM 시스템 프롬프트에 내장된 'ASR context echo 차단' 규칙에 의해 `unknown` 처리되며, 사용자 화면에는 장바구니 오작동을 차단하고 "다시 말씀해 주세요" 라는 안내를 보냅니다.

---

## 5. 운영 환경 토폴로지 변경 가이드 (IP 변경 시)

네트워크 망 변경 등으로 서버들의 IP 주소가 변경될 경우 아래 절차를 차례로 진행합니다.

1. **SSL 인증서 재발급**:
   - 변경된 노트북 및 `pai-server` IP를 반영하여 `mkcert` 명령어를 다시 실행해 인증서를 갱신합니다. (Installation 가이드 Step 2 참고)
2. **클라이언트 주소 갱신**:
   - `src/app/order_vui/kiosk.html` 및 `src/app/table_gui/table.html` 파일 상단에 정의된 `window.VOICE_SERVICE_URL` 변수의 IP 주소를 새로 변경된 `pai-server` IP로 수정합니다.
3. **배포 및 재실행**:
   - `docker-compose.ai.yml`과 `docker-compose.operation.yml` 구성 설정은 그대로 유지한 채 서비스를 각각 재기동합니다.
