from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api.endpoints import admin as admin_endpoint
from api.auth.models import User, UserRole
from api.services.aliyun_traffic import AliyunApiError, AliyunCliUnavailable


def _client(monkeypatch, query_result=None, query_error: Exception | None = None):
    async def fake_query():
        if query_error is not None:
            raise query_error
        return query_result

    async def fake_admin():
        return User(
            id=1,
            email="admin@example.test",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            role=UserRole.ADMIN,
        )

    monkeypatch.setattr(admin_endpoint, "query_current_cdt_traffic", fake_query)
    app = FastAPI()
    app.include_router(admin_endpoint.router, prefix="/api/v1/admin")
    app.dependency_overrides[admin_endpoint.require_admin] = fake_admin
    return TestClient(app)


def test_admin_aliyun_traffic_returns_current_summary(monkeypatch):
    summary = {
        "billing_cycle": "2026-08",
        "quota_gb": 20.0,
        "used_gb": 6.25,
        "remaining_gb": 13.75,
        "overage_gb": 0.0,
        "usage_percent": 31.25,
        "queried_at": "2026-08-26T14:00:00+08:00",
        "items": [],
    }

    with _client(monkeypatch, query_result=summary) as client:
        response = client.get("/api/v1/admin/aliyun-traffic")

    assert response.status_code == 200
    assert response.json() == summary


def test_admin_aliyun_traffic_reports_missing_cli(monkeypatch):
    with _client(
        monkeypatch,
        query_error=AliyunCliUnavailable("服务器未安装阿里云 CLI"),
    ) as client:
        response = client.get("/api/v1/admin/aliyun-traffic")

    assert response.status_code == 503
    assert response.json()["detail"] == "服务器未安装阿里云 CLI"


def test_admin_aliyun_traffic_reports_aliyun_api_failure(monkeypatch):
    with _client(
        monkeypatch,
        query_error=AliyunApiError("Forbidden.RAM: denied"),
    ) as client:
        response = client.get("/api/v1/admin/aliyun-traffic")

    assert response.status_code == 502
    assert response.json()["detail"] == "Forbidden.RAM: denied"
