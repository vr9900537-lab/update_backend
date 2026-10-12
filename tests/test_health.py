from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_reports_api_status() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "Custody Band Monitoring API"
    assert payload["version"] == "0.1.0"
    assert payload["firebase"]["status"] in {"not_configured", "connected", "error"}


def test_openapi_documents_health_endpoint() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/health" in paths
    assert "/api/v1/tracking/devices/{device_id}/playback" in paths
    assert "/api/v1/ingestion/simulated/events" in paths
    assert "/api/v1/reports/trips" in paths
    assert "/api/v1/reports/trips/{device_id}/rebuild" in paths
    assert "/api/v1/reports/device-assignments" in paths
    assert "/api/v1/reports/alerts.csv" in paths
    assert "/api/v1/users/{uid}/role" in paths
    assert "/api/v1/device-groups" in paths
    assert "/api/v1/tenants" in paths
    assert "/api/v1/notifications/preferences" in paths
    assert "/api/v1/audit-logs" in paths
    assert "/api/v1/devices/{device_id}/configuration" in paths
