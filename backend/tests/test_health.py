from fastapi.testclient import TestClient

from backend.main import app


def test_health_contract():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_origin_can_read_health():
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unconfigured_origin_is_not_granted_cors_access():
    with TestClient(app) as client:
        response = client.get(
            "/health", headers={"Origin": "https://untrusted.example"}
        )
    assert "access-control-allow-origin" not in response.headers
