from typing import Any

from fastapi.testclient import TestClient

from app.core import auth
from app.main import app

client = TestClient(app)


class FakeSnapshot:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self.data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return self.data


class FakeDocument:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self.data = data

    def get(self) -> FakeSnapshot:
        return FakeSnapshot(self.data)


class FakeCollection:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self.data = data

    def document(self, uid: str) -> FakeDocument:
        return FakeDocument(self.data)


class FakeDatabase:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self.data = data

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.data)


class FakeFirebaseClient:
    def __init__(self, profile: dict[str, Any] | None) -> None:
        self.profile = profile

    def get_app(self) -> object:
        return object()

    def get_database(self) -> FakeDatabase:
        return FakeDatabase(self.profile)


def configure_auth(
    monkeypatch: Any,
    profile: dict[str, Any] | None,
    claims: dict[str, Any] | None = None,
) -> None:
    monkeypatch.setattr(
        auth,
        "get_firebase_client",
        lambda: FakeFirebaseClient(profile),
    )
    monkeypatch.setattr(
        auth.firebase_auth,
        "verify_id_token",
        lambda token, app, check_revoked: claims or {"uid": "user-123"},
    )


def test_user_profile_requires_bearer_token() -> None:
    response = client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_user_profile_uses_verified_uid_and_firestore_role(
    monkeypatch: Any,
) -> None:
    configure_auth(
        monkeypatch,
        {"display_name": "Test Officer", "role": "monitoring_officer", "status": "active"},
        {"uid": "verified-uid", "email": "officer@example.test"},
    )

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer valid-test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "uid": "verified-uid",
        "email": "officer@example.test",
        "display_name": "Test Officer",
        "role": "monitoring_officer",
        "status": "active",
        "tenant_id": None,
    }


def test_inactive_user_profile_is_denied(monkeypatch: Any) -> None:
    configure_auth(
        monkeypatch,
        {"role": "monitoring_officer", "status": "inactive"},
    )

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer valid-test-token"},
    )

    assert response.status_code == 403


def test_non_admin_cannot_list_user_profiles(monkeypatch: Any) -> None:
    configure_auth(
        monkeypatch,
        {"role": "monitoring_officer", "status": "active"},
    )

    response = client.get(
        "/api/v1/users",
        headers={"Authorization": "Bearer valid-test-token"},
    )

    assert response.status_code == 403


def test_user_without_firestore_profile_is_denied(monkeypatch: Any) -> None:
    configure_auth(monkeypatch, None)

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer valid-test-token"},
    )

    assert response.status_code == 403


def test_invalid_firebase_token_is_rejected(monkeypatch: Any) -> None:
    monkeypatch.setattr(auth, "get_firebase_client", lambda: FakeFirebaseClient(None))

    def reject_token(token: str, app: object, check_revoked: bool) -> dict[str, Any]:
        raise auth.firebase_auth.InvalidIdTokenError("invalid token")

    monkeypatch.setattr(auth.firebase_auth, "verify_id_token", reject_token)

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer invalid-test-token"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
