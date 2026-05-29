from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api.endpoints import admin as admin_endpoint
from api.auth.models import User, UserRole
from core import runtime_quality_report as quality_module
from core.runtime_v2 import RuntimeV2Store


def test_admin_diagnostics_exposes_runtime_v2_quality_report(tmp_path, monkeypatch):
    runtime_store = RuntimeV2Store(tmp_path / "runtime.db")
    session = runtime_store.ensure_session(
        session_id="web:quality:main",
        kind="web_workspace",
        platform="web",
        platform_user_id="quality",
    )
    turn = runtime_store.create_turn(
        session_id=session["id"],
        input_text="失败任务",
        kernel_provider="codex",
    )
    runtime_store.update_turn_status(turn["id"], "running")
    runtime_store.update_turn_status(
        turn["id"],
        "failed",
        error="codex timeout while generating report",
    )
    artifact_path = tmp_path / "missing.mp4"
    artifact = runtime_store.record_artifact(
        session_id=session["id"],
        turn_id=turn["id"],
        kind="video",
        path=str(artifact_path),
        filename="missing.mp4",
    )
    runtime_store.record_delivery(
        artifact_id=artifact["id"],
        platform="weixin",
        target="weixin:chat",
        status="failed",
        error="upload failed",
    )
    runtime_store.append_event(
        session_id=session["id"],
        turn_id=turn["id"],
        event_type="kernel.error",
        payload={"message": "timeout"},
    )
    monkeypatch.setattr(quality_module, "runtime_v2", runtime_store)

    async def _operator():
        return User(
            id=1,
            email="operator@example.test",
            hashed_password="x",
            is_active=True,
            is_verified=True,
            role=UserRole.OPERATOR,
        )

    app = FastAPI()
    app.include_router(admin_endpoint.router, prefix="/api/v1/admin")
    app.dependency_overrides[admin_endpoint.require_operator] = _operator

    with TestClient(app) as client:
        response = client.get("/api/v1/admin/diagnostics")

    assert response.status_code == 200
    quality = response.json()["runtime_v2_quality"]
    assert quality["status_counts"]["failed"] == 1
    assert quality["artifact_delivery_failed"] == 1
    assert quality["kernel_timeouts"] == 1
    assert any("artifact delivery receipt" in item for item in quality["recommendations"])
    assert quality["delivery_failure_counts"] == {"weixin:video": 1}
    assert quality["recent_failed_turns"][0]["turn_id"] == turn["id"]
    assert quality["recent_failed_turns"][0]["trace_path"] == (
        "/api/v1/web-chat/sessions/web:quality:main/trace"
    )
    assert quality["recent_delivery_failures"][0]["artifact_filename"] == "missing.mp4"
    assert quality["recent_delivery_failures"][0]["session_id"] == "web:quality:main"
    assert quality["recent_delivery_failures"][0]["trace_path"] == (
        "/api/v1/web-chat/sessions/web:quality:main/trace"
    )
    assert any("weixin video artifact delivery" in item for item in quality["suggested_tests"])
