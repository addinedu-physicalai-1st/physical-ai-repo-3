import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import order_repo, table_repo


@pytest.fixture(autouse=True)
def reset_state():
    table_repo.reset()
    order_repo.reset()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
