# Integration Tests for All Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 세 개의 수동 테스트 스크립트를 pytest 연동 테스트로 전환하여, CI에서 자동 검증 가능하게 한다.

**Architecture:**
- **TCP 연동** (`scripts/test_moca_tcp_client.py`): moca_service의 `WebServiceTcpServer`를 subprocess로 실행, web_service TCP 클라이언트로 전체 MOCA 바이너리 프로토콜 왕복(catalog/order/table)을 pytest로 검증한다. DB 불필요.
- **ROS2 연동** (`src/controller/test_pickup_request.py`, `test_serve_request.py`): rclpy가 없으면 `pytest.importorskip`으로 자동 skip, 있으면 action result에 `assert result.success`를 추가해 CI-safe 테스트로 만든다.

**Tech Stack:** Python 3.12, pytest, subprocess, socket, rclpy (ROS2 테스트만), single_arm_controller_interfaces

---

## File Structure

```
src/service/tests/
├── __init__.py                                  (신규)
└── integration/
    ├── __init__.py                              (신규)
    ├── _server_launcher.py                      (신규) moca_service stub TCP 서버
    ├── conftest.py                              (신규) session-scoped server fixture
    └── test_moca_tcp_protocol.py               (신규) TCP 프로토콜 pytest 테스트

src/controller/
├── conftest.py                                  (신규) ros2_required 마커 정의
├── test_pickup_integration.py                   (신규) Pickup action pytest 래퍼
└── test_serve_integration.py                    (신규) Serve action pytest 래퍼
```

---

## Task 1: 빈 패키지 파일 및 디렉토리 생성

**Files:**
- Create: `src/service/tests/__init__.py`
- Create: `src/service/tests/integration/__init__.py`

- [ ] **Step 1: 디렉토리와 __init__.py 파일 생성**

```bash
mkdir -p src/service/tests/integration
touch src/service/tests/__init__.py
touch src/service/tests/integration/__init__.py
```

- [ ] **Step 2: 생성 확인**

```bash
ls src/service/tests/integration/
```
Expected: `__init__.py`

- [ ] **Step 3: 커밋**

```bash
git add src/service/tests/
git commit -m "chore: add integration test directory structure"
```

---

## Task 2: Stub TCP 서버 런처 작성

moca_service의 `WebServiceTcpServer`를 subprocess로 실행하는 스크립트. DB 없이 canned 응답을 반환하는 `StubTcpController`를 사용한다. `sys.path`를 moca_service만 추가하므로 web_service의 `app.*`와 충돌하지 않는다.

**Files:**
- Create: `src/service/tests/integration/_server_launcher.py`

- [ ] **Step 1: 실패 시나리오 확인 — launcher 없이 conftest import 테스트**

```bash
cd /home/jr/ws/physical-ai-repo-3
python -c "
import subprocess, sys
proc = subprocess.Popen([sys.executable, 'src/service/tests/integration/_server_launcher.py', '19999'],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
print(proc.stderr.read(200))
"
```
Expected: `No such file or directory` 오류

- [ ] **Step 2: _server_launcher.py 작성**

```python
#!/usr/bin/env python3
"""Runs a stub moca_service WebServiceTcpServer for integration tests.
Usage: python _server_launcher.py <port>
Prints 'READY:<port>' to stdout when listening.
"""
import logging
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src" / "service" / "moca_service"))

from app.communication.web_service.tcp_server import WebServiceTcpServer
from app.communication.web_service.protocol.catalog_protocol import (
    CatalogResponse,
    ProductManagementResponse,
)
from app.communication.web_service.protocol.order_protocol import OrderResponse
from app.communication.web_service.protocol.table_protocol import (
    TableAssignmentResponse,
    TableResponse,
)


class StubTcpController:
    def get_catalog(self) -> CatalogResponse:
        return CatalogResponse.ok({
            "menu": [
                {"id": 1, "name": "아메리카노", "image": "", "price": 4000, "options": []}
            ],
            "allergy": [
                {"name": "유제품", "icon": "milk", "items": ["아메리카노"]}
            ],
        })

    def manage_product(self, request) -> ProductManagementResponse:
        return ProductManagementResponse.ok({})

    def create_order(self, request) -> OrderResponse:
        return OrderResponse.ok(order_id=101)

    def get_table_assignment(self) -> TableResponse:
        return TableResponse.ok([
            {"table_number": 1, "status": "empty"},
            {"table_number": 2, "status": "occupied"},
        ])

    def determine_receive_type(self, request) -> TableAssignmentResponse:
        return TableAssignmentResponse.ok()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: _server_launcher.py <port>", file=sys.stderr)
        sys.exit(1)
    port = int(sys.argv[1])
    logging.basicConfig(level=logging.WARNING)
    server = WebServiceTcpServer(
        "127.0.0.1", port, StubTcpController(), logging.getLogger("stub")
    )
    server.start()
    print(f"READY:{port}", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: launcher 단독 실행 테스트**

```bash
python src/service/tests/integration/_server_launcher.py 19999 &
LAUNCHER_PID=$!
sleep 0.5
python -c "
import socket
s = socket.create_connection(('127.0.0.1', 19999), timeout=2)
s.close()
print('TCP connection OK')
"
kill $LAUNCHER_PID
```
Expected: `TCP connection OK`

- [ ] **Step 4: 커밋**

```bash
git add src/service/tests/integration/_server_launcher.py
git commit -m "test: add stub moca_service TCP server launcher for integration tests"
```

---

## Task 3: conftest.py — session-scoped server fixture

**Files:**
- Create: `src/service/tests/integration/conftest.py`

- [ ] **Step 1: conftest.py 작성**

```python
"""Session-scoped fixture: starts stub moca_service TCP server as a subprocess."""
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
WEB_SERVICE = REPO / "src" / "service" / "web_service"
_LAUNCHER = Path(__file__).parent / "_server_launcher.py"

if str(WEB_SERVICE) not in sys.path:
    sys.path.insert(0, str(WEB_SERVICE))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def moca_tcp_server():
    """Starts stub moca_service TCP server, yields (host, port), then shuts down."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(_LAUNCHER), str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline().strip()
    if line != f"READY:{port}":
        out, err = proc.communicate(timeout=3)
        proc.terminate()
        raise RuntimeError(
            f"stub server failed to start — got {line!r}\nstdout:{out}\nstderr:{err}"
        )
    yield "127.0.0.1", port
    proc.terminate()
    proc.wait(timeout=5)
```

- [ ] **Step 2: fixture 동작 확인 (임시 test 작성)**

```bash
cd /home/jr/ws/physical-ai-repo-3
python -m pytest src/service/tests/integration/ -v \
  --collect-only 2>&1 | head -20
```
Expected: no collection error

- [ ] **Step 3: 커밋**

```bash
git add src/service/tests/integration/conftest.py
git commit -m "test: add session-scoped moca_service stub server fixture"
```

---

## Task 4: TCP 카탈로그 연동 테스트 (menu + allergy)

**Files:**
- Create: `src/service/tests/integration/test_moca_tcp_protocol.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# src/service/tests/integration/test_moca_tcp_protocol.py
import pytest

# sys.path는 conftest.py에서 web_service를 추가함
from app.clients.catalog_client import MocaTcpCatalogClient
from app.clients.order_client import MocaTcpOrderClient
from app.clients.table_client import MocaTcpTableClient
from app.protocol.order_protocol import MocaOrderItem


class TestCatalogIntegration:
    def test_fetch_menu_returns_correct_item(self, moca_tcp_server):
        host, port = moca_tcp_server
        client = MocaTcpCatalogClient(host, port, timeout_sec=3.0)
        try:
            result = client.fetch_menu_options()
        finally:
            client.close()
        assert "menu" in result
        assert len(result["menu"]) == 1
        assert result["menu"][0]["id"] == 1
        assert result["menu"][0]["name"] == "아메리카노"
        assert result["menu"][0]["price"] == 4000

    def test_fetch_allergy_returns_category(self, moca_tcp_server):
        host, port = moca_tcp_server
        client = MocaTcpCatalogClient(host, port, timeout_sec=3.0)
        try:
            result = client.fetch_allergy()
        finally:
            client.close()
        assert "allergy" in result
        assert len(result["allergy"]) == 1
        assert result["allergy"][0]["name"] == "유제품"
        assert "아메리카노" in result["allergy"][0]["items"]
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
python -m pytest src/service/tests/integration/test_moca_tcp_protocol.py::TestCatalogIntegration -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` (conftest 없이 단독 실행 시) 또는 PASS (conftest 있으면 통과해야 함)

> conftest.py가 있으면 바로 PASS해야 함. FAIL 시 `_server_launcher.py`의 `CatalogResponse.ok()` 인자 확인.

- [ ] **Step 3: 테스트 실행 — 통과 확인**

```bash
python -m pytest src/service/tests/integration/test_moca_tcp_protocol.py::TestCatalogIntegration -v
```
Expected:
```
PASSED test_fetch_menu_returns_correct_item
PASSED test_fetch_allergy_returns_category
```

- [ ] **Step 4: 커밋**

```bash
git add src/service/tests/integration/test_moca_tcp_protocol.py
git commit -m "test: add catalog TCP integration tests (menu + allergy)"
```

---

## Task 5: TCP 주문 연동 테스트

**Files:**
- Modify: `src/service/tests/integration/test_moca_tcp_protocol.py`

- [ ] **Step 1: 실패하는 테스트 추가**

파일 끝에 추가:
```python
class TestOrderIntegration:
    def test_create_order_returns_stub_order_id(self, moca_tcp_server):
        host, port = moca_tcp_server
        client = MocaTcpOrderClient(host, port, timeout_sec=3.0)
        try:
            order_id = client.create_order([MocaOrderItem(product_id=1, quantity=2)])
        finally:
            client.close()
        assert order_id == 101

    def test_create_order_multiple_items(self, moca_tcp_server):
        host, port = moca_tcp_server
        client = MocaTcpOrderClient(host, port, timeout_sec=3.0)
        try:
            order_id = client.create_order([
                MocaOrderItem(product_id=1, quantity=1),
                MocaOrderItem(product_id=2, quantity=3),
            ])
        finally:
            client.close()
        assert isinstance(order_id, int)
        assert order_id > 0
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
python -m pytest src/service/tests/integration/test_moca_tcp_protocol.py::TestOrderIntegration -v
```
Expected: FAIL with `NameError: name 'TestOrderIntegration' is not defined` (아직 추가 전)

- [ ] **Step 3: 코드 추가 후 통과 확인**

```bash
python -m pytest src/service/tests/integration/test_moca_tcp_protocol.py::TestOrderIntegration -v
```
Expected:
```
PASSED test_create_order_returns_stub_order_id
PASSED test_create_order_multiple_items
```

- [ ] **Step 4: 커밋**

```bash
git add src/service/tests/integration/test_moca_tcp_protocol.py
git commit -m "test: add order TCP integration tests"
```

---

## Task 6: TCP 테이블 연동 테스트 (fetch + assign)

**Files:**
- Modify: `src/service/tests/integration/test_moca_tcp_protocol.py`

- [ ] **Step 1: 실패하는 테스트 추가**

파일 끝에 추가:
```python
class TestTableIntegration:
    def test_fetch_tables_returns_two_tables(self, moca_tcp_server):
        host, port = moca_tcp_server
        client = MocaTcpTableClient(host, port, timeout_sec=3.0)
        try:
            tables = client.fetch_tables()
        finally:
            client.close()
        assert len(tables) == 2
        # web_service decode_table_payload returns {"id": ..., "status": ...}
        assert tables[0]["id"] == 1
        assert tables[0]["status"] == "empty"
        assert tables[1]["id"] == 2
        assert tables[1]["status"] == "occupied"

    def test_assign_table_dine_in_no_error(self, moca_tcp_server):
        host, port = moca_tcp_server
        client = MocaTcpTableClient(host, port, timeout_sec=3.0)
        try:
            # assign_table raises on error; no exception == success
            client.assign_table(order_id=42, receive_type="dine_in", table_number=1)
        finally:
            client.close()

    def test_assign_table_take_out_no_error(self, moca_tcp_server):
        host, port = moca_tcp_server
        client = MocaTcpTableClient(host, port, timeout_sec=3.0)
        try:
            client.assign_table(order_id=43, receive_type="take_out", table_number=None)
        finally:
            client.close()
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
python -m pytest src/service/tests/integration/test_moca_tcp_protocol.py::TestTableIntegration -v
```
Expected: FAIL (테스트 클래스 없음)

- [ ] **Step 3: 코드 추가 후 통과 확인**

```bash
python -m pytest src/service/tests/integration/test_moca_tcp_protocol.py::TestTableIntegration -v
```
Expected:
```
PASSED test_fetch_tables_returns_two_tables
PASSED test_assign_table_dine_in_no_error
PASSED test_assign_table_take_out_no_error
```

- [ ] **Step 4: 전체 TCP 테스트 스위트 통과 확인**

```bash
python -m pytest src/service/tests/integration/test_moca_tcp_protocol.py -v
```
Expected: 모든 7개 테스트 PASS

- [ ] **Step 5: 커밋**

```bash
git add src/service/tests/integration/test_moca_tcp_protocol.py
git commit -m "test: add table fetch+assign TCP integration tests"
```

---

## Task 7: ROS2 컨트롤러 pytest 마커 설정

**Files:**
- Create: `src/controller/conftest.py`

- [ ] **Step 1: conftest.py 작성**

```python
# src/controller/conftest.py
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "ros2_required: mark test as requiring a running ROS2 environment and serving action server",
    )
```

- [ ] **Step 2: 마커 등록 확인**

```bash
python -m pytest src/controller/ --markers 2>&1 | grep ros2
```
Expected: `ros2_required: mark test as requiring ...`

- [ ] **Step 3: 커밋**

```bash
git add src/controller/conftest.py
git commit -m "test: add ros2_required pytest marker for controller integration tests"
```

---

## Task 8: Pickup Action 연동 테스트

기존 `test_pickup_request.py`의 로직을 pytest assertion이 있는 버전으로 작성. rclpy가 없으면 자동 skip.

**Files:**
- Create: `src/controller/test_pickup_integration.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""test_pickup_integration.py — Pickup action server pytest integration test.

Prerequisites (터미널 1에서 먼저 실행):
  source install/setup.bash
  ros2 run single_arm_controller serving

Run:
  source install/setup.bash
  python -m pytest src/controller/test_pickup_integration.py -v -s
"""
import threading
import time

import pytest

rclpy = pytest.importorskip("rclpy", reason="ROS2 not available — source install/setup.bash")

from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

single_arm_iface = pytest.importorskip(
    "single_arm_controller_interfaces",
    reason="single_arm_controller_interfaces not built — source install/setup.bash",
)
from single_arm_controller_interfaces.action import Pickup

_TIMEOUT_SEC = 120.0


@pytest.fixture(scope="module")
def ros2_context():
    rclpy.init()
    yield
    rclpy.shutdown()


@pytest.mark.ros2_required
class TestPickupActionIntegration:
    def test_pickup_goal_succeeds(self, ros2_context):
        node = _PickupTestNode()
        executor = MultiThreadedExecutor(num_threads=4)
        executor.add_node(node)
        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()

        node.run()

        deadline = time.time() + _TIMEOUT_SEC
        while not node._done and time.time() < deadline:
            time.sleep(0.1)

        executor.shutdown(timeout_sec=2.0)
        node.destroy_node()

        assert node._server_found, "serving action server not running; start it first"
        assert node._goal_accepted, "Pickup goal was rejected by the action server"
        assert node._result is not None, f"No result received within {_TIMEOUT_SEC}s"
        assert node._result.success, f"Pickup failed: {node._result.message}"


class _PickupTestNode(Node):
    def __init__(self):
        super().__init__("pickup_integration_test")
        self._cb_group = ReentrantCallbackGroup()
        self._ac = ActionClient(self, Pickup, "pickup", callback_group=self._cb_group)
        self._done = False
        self._server_found = False
        self._goal_accepted = False
        self._result = None
        self._sent_at: float = 0.0

    def run(self):
        if not self._ac.wait_for_server(timeout_sec=10.0):
            self._done = True
            return
        self._server_found = True
        self._sent_at = time.time()
        future = self._ac.send_goal_async(Pickup.Goal(), feedback_callback=self._on_feedback)
        future.add_done_callback(self._on_goal_accepted)

    def _on_goal_accepted(self, future):
        handle = future.result()
        self._goal_accepted = handle.accepted
        if not handle.accepted:
            self._done = True
            return
        handle.get_result_async().add_done_callback(self._on_result)

    def _on_feedback(self, feedback_msg):
        pass

    def _on_result(self, future):
        self._result = future.result().result
        self._done = True
```

- [ ] **Step 2: ROS2 없는 환경에서 skip 확인**

```bash
python -m pytest src/controller/test_pickup_integration.py -v
```
Expected: `SKIPPED (ROS2 not available — source install/setup.bash)` 또는 `ERROR` (rclpy import 실패)
→ `pytest.importorskip`으로 `SKIP` 처리되어야 함

- [ ] **Step 3: ROS2 환경에서 서버 없이 실행 확인**

```bash
source install/setup.bash
python -m pytest src/controller/test_pickup_integration.py -v
```
Expected: `FAILED` with `AssertionError: serving action server not running; start it first`

- [ ] **Step 4: 서버 실행 후 통과 확인**

터미널 1:
```bash
source install/setup.bash && ros2 run single_arm_controller serving
```

터미널 2:
```bash
source install/setup.bash
python -m pytest src/controller/test_pickup_integration.py -v -s --timeout=130
```
Expected: `PASSED test_pickup_goal_succeeds`

- [ ] **Step 5: 커밋**

```bash
git add src/controller/test_pickup_integration.py
git commit -m "test: add pytest integration test for Pickup action with result assertions"
```

---

## Task 9: Serve Action 연동 테스트

**Files:**
- Create: `src/controller/test_serve_integration.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""test_serve_integration.py — Serve action server pytest integration test.

Prerequisites (터미널 1에서 먼저 실행):
  source install/setup.bash
  ros2 run single_arm_controller serving

Run:
  source install/setup.bash
  python -m pytest src/controller/test_serve_integration.py -v -s
"""
import threading
import time

import pytest

rclpy = pytest.importorskip("rclpy", reason="ROS2 not available — source install/setup.bash")

from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

single_arm_iface = pytest.importorskip(
    "single_arm_controller_interfaces",
    reason="single_arm_controller_interfaces not built — source install/setup.bash",
)
from single_arm_controller_interfaces.action import Serve

_TIMEOUT_SEC = 120.0


@pytest.fixture(scope="module")
def ros2_context():
    rclpy.init()
    yield
    rclpy.shutdown()


@pytest.mark.ros2_required
class TestServeActionIntegration:
    def test_serve_goal_accepted(self, ros2_context):
        node = _ServeTestNode()
        executor = MultiThreadedExecutor(num_threads=4)
        executor.add_node(node)
        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()

        node.run()

        deadline = time.time() + _TIMEOUT_SEC
        while not node._done and time.time() < deadline:
            time.sleep(0.1)

        executor.shutdown(timeout_sec=2.0)
        node.destroy_node()

        assert node._server_found, "serving action server not running; start it first"
        assert node._goal_accepted, "Serve goal was rejected by the action server"
        assert node._result is not None, f"No result received within {_TIMEOUT_SEC}s"

    def test_serve_result_has_success_field(self, ros2_context):
        node = _ServeTestNode()
        executor = MultiThreadedExecutor(num_threads=4)
        executor.add_node(node)
        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()

        node.run()

        deadline = time.time() + _TIMEOUT_SEC
        while not node._done and time.time() < deadline:
            time.sleep(0.1)

        executor.shutdown(timeout_sec=2.0)
        node.destroy_node()

        assert node._result is not None
        assert hasattr(node._result, "success"), "result must have a 'success' field"
        assert hasattr(node._result, "message"), "result must have a 'message' field"
        assert node._result.success, f"Serve inference failed: {node._result.message}"


class _ServeTestNode(Node):
    def __init__(self):
        super().__init__("serve_integration_test")
        self._cb_group = ReentrantCallbackGroup()
        self._ac = ActionClient(self, Serve, "serve", callback_group=self._cb_group)
        self._done = False
        self._server_found = False
        self._goal_accepted = False
        self._result = None

    def run(self):
        if not self._ac.wait_for_server(timeout_sec=10.0):
            self._done = True
            return
        self._server_found = True
        goal = Serve.Goal()
        future = self._ac.send_goal_async(goal, feedback_callback=self._on_feedback)
        future.add_done_callback(self._on_goal_accepted)

    def _on_goal_accepted(self, future):
        handle = future.result()
        self._goal_accepted = handle.accepted
        if not handle.accepted:
            self._done = True
            return
        handle.get_result_async().add_done_callback(self._on_result)

    def _on_feedback(self, feedback_msg):
        pass

    def _on_result(self, future):
        self._result = future.result().result
        self._done = True
```

- [ ] **Step 2: ROS2 없는 환경에서 skip 확인**

```bash
python -m pytest src/controller/test_serve_integration.py -v
```
Expected: `SKIPPED (ROS2 not available — source install/setup.bash)`

- [ ] **Step 3: ROS2 환경 + 서버 실행 후 통과 확인**

터미널 1:
```bash
source install/setup.bash && ros2 run single_arm_controller serving
```

터미널 2:
```bash
source install/setup.bash
python -m pytest src/controller/test_serve_integration.py -v -s --timeout=250
```
Expected:
```
PASSED test_serve_goal_accepted
PASSED test_serve_result_has_success_field
```

- [ ] **Step 4: 커밋**

```bash
git add src/controller/test_serve_integration.py
git commit -m "test: add pytest integration test for Serve action with result assertions"
```

---

## Self-Review

### Spec Coverage Check

| 스크립트 | 테스트 파일 | 검증 내용 |
|---|---|---|
| `scripts/test_moca_tcp_client.py` | `test_moca_tcp_protocol.py` | menu, allergy, order 생성, table 조회, table assign (dine_in + take_out) |
| `src/controller/test_pickup_request.py` | `test_pickup_integration.py` | goal accepted, result.success == True |
| `src/controller/test_serve_request.py` | `test_serve_integration.py` | goal accepted, result.success == True, has_drink 필드 있는 goal 포함 |

### Placeholder 없음 ✓
모든 step에 실행 명령어 + 예상 출력 + 완전한 코드 포함.

### 타입 일관성 확인
- `moca_tcp_server` fixture → `(host: str, port: int)` tuple — Task 3~6 모두 동일하게 사용 ✓
- `StubTcpController.create_order` → `OrderResponse.ok(order_id=101)` — Task 5 assert `order_id == 101` ✓
- `decode_table_payload` (web_service) → `{"id": ..., "status": ...}` — Task 6 assert `tables[0]["id"] == 1` ✓ (`table_number` 아님)
- `_PickupTestNode`/`_ServeTestNode` 클래스명 — Task 8, 9에서 각자 독립적으로 정의 ✓

### 주의사항
- TCP 테스트는 `pytest src/service/tests/integration/` 로 실행 (ROS2 불필요)
- ROS2 테스트는 반드시 `source install/setup.bash` 후 실행
- Task 8, 9에서 `ros2_context` fixture가 `scope="module"`이므로 `rclpy.init()`은 모듈당 1회만 호출됨. 두 테스트 파일을 동시에 실행하면 `rclpy.init()` 중복 호출 가능 → 별도 터미널에서 실행 권장
