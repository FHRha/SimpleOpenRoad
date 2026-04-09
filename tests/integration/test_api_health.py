import os

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint() -> None:
    os.environ["APP_CONFIG_PATH"] = "tests/fixtures/sample_config.yaml"
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["providers"] >= 1
