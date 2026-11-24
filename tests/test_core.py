"""Automated test suite verifying OmniPilot Hub core features, smart alarm escalation, and security."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app


@pytest.fixture()
def test_client(tmp_path: Path):
    settings = Settings(
        api_auth_token="test_secret_token_boss",
        pc_fallback_siren_enabled=False,
        ntfy_topic="",
        macrodroid_webhook_url="",
        pushover_app_token="",
        telegram_bot_token="",
        gemini_api_key="",
        whatsapp_enabled=False,
    )
    app = create_app(settings_override=settings, start_daemons=False)
    # Isolate SQLite DB in temp dir for clean repeatable tests
    app.state.container.db.db_path = tmp_path / "test_omnipilot.db"
    with TestClient(app) as client:
        yield client, app.state.container


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test_secret_token_boss"}


def test_health_and_auth_guard(test_client):
    client, _ = test_client
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/status").status_code == 401
    res = client.get("/api/status", headers=auth_headers())
    assert res.status_code == 200
    data = res.json()
    assert "telemetry" in data
    assert "phone_presence" in data
    assert "today_schedule" in data


def test_schedule_and_daily_briefing(test_client):
    client, _ = test_client
    today = datetime.now().strftime("%Y-%m-%d")
    create_res = client.post(
        "/api/schedules",
        headers=auth_headers(),
        json={
            "title": "Submit Tugas Algoritma di LMS",
            "event_date": today,
            "start_time": "10:00",
            "alarm_enabled": True,
            "alarm_timeout_minutes": 5,
        },
    )
    assert create_res.status_code == 200
    item = create_res.json()
    assert item["title"] == "Submit Tugas Algoritma di LMS"

    today_res = client.get("/api/schedules/today", headers=auth_headers())
    assert today_res.status_code == 200
    body = today_res.json()
    assert body["count"] >= 1
    assert "Submit Tugas Algoritma di LMS" in body["briefing"]


@pytest.mark.asyncio
async def test_smart_alarm_escalation_and_phone_heartbeat(test_client):
    client, container = test_client

    # 1. Arm an escalation alarm
    arm_res = client.post(
        "/api/alarms/arm",
        headers=auth_headers(),
        json={"title": "Cek Deadline Penting", "timeout_minutes": 4, "message": "Segera cek HP"},
    )
    assert arm_res.status_code == 200
    alarm = arm_res.json()
    assert alarm["status"] == "ARMED"

    # 2. Simulate time passing halfway -> WARNING (Stage 2)
    created_past = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    deadline_soon = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    await container.db.conn.execute(
        "UPDATE alarm_watchdogs SET created_at = ?, deadline_at = ? WHERE id = ?",
        (created_past, deadline_soon, alarm["id"]),
    )
    await container.db.conn.commit()
    await container.scheduler._evaluate_active_alarms()

    mid_state = await container.db.get_alarm_watchdog(alarm["id"])
    assert mid_state["status"] == "WARNING"
    assert mid_state["stage"] == 2

    # 3. Simulate timer expiring with NO phone check -> CRITICAL (Stage 3)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    await container.db.conn.execute(
        "UPDATE alarm_watchdogs SET deadline_at = ? WHERE id = ?",
        (expired, alarm["id"]),
    )
    await container.db.conn.commit()
    await container.scheduler._evaluate_active_alarms()

    crit_state = await container.db.get_alarm_watchdog(alarm["id"])
    assert crit_state["status"] == "CRITICAL"
    assert crit_state["stage"] == 3

    # 4. Explicit ACK disarms critical alarm and records phone check
    ack_res = client.post(f"/api/alarms/{alarm['id']}/ack", headers=auth_headers())
    assert ack_res.status_code == 200
    assert ack_res.json()["status"] == "ACKNOWLEDGED"

    # 5. Phone screen unlock heartbeat auto-disarms ARMED waiting alarm
    arm2 = client.post(
        "/api/alarms/arm",
        headers=auth_headers(),
        json={"title": "Pengingat Kuliah", "timeout_minutes": 5},
    ).json()
    hb = client.post(
        "/api/phone/heartbeat",
        headers=auth_headers(),
        json={"event_type": "screen_unlock", "device_name": "android", "battery_pct": 85},
    )
    assert hb.status_code == 200
    assert any(a["id"] == arm2["id"] for a in hb.json()["disarmed_alarms"])


def test_approval_gate_and_document_generation(test_client):
    client, _ = test_client

    # Risky shell command must go through Approval Gate
    cmd_res = client.post(
        "/api/pc/command",
        headers=auth_headers(),
        json={"command": "shutdown /s /t 0"},
    )
    assert cmd_res.status_code == 200
    assert cmd_res.json()["status"] == "pending_approval"
    apr_id = cmd_res.json()["approval_id"]

    # Rejecting it cleanly resolves without executing
    rej = client.post(
        f"/api/approvals/{apr_id}/reject",
        headers=auth_headers(),
        json={"reason": "Tes keamanan"},
    )
    assert rej.status_code == 200
    assert rej.json()["status"] == "REJECTED"

    # Document creation (DOCX + PDF + MD) with cleanup
    created_paths: list[Path] = []
    try:
        for fmt in ("docx", "pdf", "md"):
            doc_res = client.post(
                "/api/documents",
                headers=auth_headers(),
                json={
                    "title": f"Laporan Uji {fmt.upper()}",
                    "fmt": fmt,
                    "sections": [{"heading": "Pendahuluan", "content": "Konten uji otomatis."}],
                },
            )
            assert doc_res.status_code == 200
            doc = doc_res.json()
            created_paths.append(Path(doc["path"]))
            assert doc["size_bytes"] > 0
            dl = client.get(doc["download_url"], headers=auth_headers())
            assert dl.status_code == 200
    finally:
        for p in created_paths:
            if p.exists():
                p.unlink()


def test_pwa_frontend_and_chat_commands(test_client):
    client, _ = test_client

    # Verify Glassmorphism PWA static assets mount cleanly
    assert client.get("/").status_code == 200
    assert "OmniPilot Hub" in client.get("/").text
    assert client.get("/css/styles.css").status_code == 200
    assert client.get("/js/app.js").status_code == 200
    assert client.get("/manifest.json").status_code == 200

    # Verify remote chat slash commands work immediately
    for prompt, expected in [
        ("/help", "Daftar perintah cepat"),
        ("/jadwal", "Jadwal Boss"),
        ("/pc", "Status PC"),
    ]:
        res = client.post(
            "/api/chat",
            headers=auth_headers(),
            json={"prompt": prompt, "channel": "web"},
        )
        assert res.status_code == 200
        assert expected in res.json()["reply"]


def test_remote_input_security_guard(tmp_path: Path):
    """Verify remote mouse/keyboard endpoints enforce auth and REMOTE_INPUT_ENABLED guard."""
    settings = Settings(
        api_auth_token="test_secret_token_boss",
        remote_input_enabled=False,
        pc_fallback_siren_enabled=False,
    )
    app = create_app(settings_override=settings, start_daemons=False)
    app.state.container.db.db_path = tmp_path / "test_input_guard.db"

    with TestClient(app) as client:
        # Unauthenticated rejected
        assert client.post("/api/pc/mouse", json={"action": "click"}).status_code == 401
        # Authenticated but disabled returns 403
        r_mouse = client.post(
            "/api/pc/mouse",
            headers=auth_headers(),
            json={"action": "click", "x_ratio": 0.5, "y_ratio": 0.5},
        )
        assert r_mouse.status_code == 403
        r_kb = client.post(
            "/api/pc/keyboard",
            headers=auth_headers(),
            json={"hotkey": "enter"},
        )
        assert r_kb.status_code == 403


def test_multi_provider_models_command(tmp_path: Path):
    """Verify /models reports all configured free-tier AI providers in waterfall order."""
    settings = Settings(
        api_auth_token="test_secret_token_boss",
        gemini_api_key="dummy_gem",
        groq_api_key="dummy_groq",
        cerebras_api_key="dummy_cerebras",
        openrouter_api_key="dummy_or",
        ollama_model="qwen2.5:7b",
        pc_fallback_siren_enabled=False,
    )
    app = create_app(settings_override=settings, start_daemons=False)
    app.state.container.db.db_path = tmp_path / "test_models.db"

    with TestClient(app) as client:
        res = client.post("/api/chat", headers=auth_headers(), json={"prompt": "/models", "channel": "web"})
        assert res.status_code == 200
        reply = res.json()["reply"]
        assert "GEMINI" in reply
        assert "GROQ" in reply
        assert "CEREBRAS" in reply
        assert "OPENROUTER" in reply
        assert "OLLAMA" in reply


def test_wave1_memory_top_and_tunnel_extraction(test_client):
    """Verify Wave 1 features: long-term memory commands, /top RAM process inspector, and tunnel URL extraction."""
    from backend.core.runtime_state import extract_tunnel_url

    client, _ = test_client

    # 1. Verify Cloudflare quick-tunnel URL extractor ignores api.trycloudflare.com and local 127.0.0.1
    assert extract_tunnel_url("Membuka ke http://127.0.0.1:8787") is None
    assert extract_tunnel_url("https://api.trycloudflare.com/tunnel") is None
    sample_line = "2026-11-23T05:32:57Z INF |  https://computational-architecture-reload-identified.trycloudflare.com  |"
    assert extract_tunnel_url(sample_line) == "https://computational-architecture-reload-identified.trycloudflare.com"

    # 2. Verify /ingat, /memori, /lupa, and /top slash commands
    r_save = client.post(
        "/api/chat",
        headers=auth_headers(),
        json={"prompt": "/ingat Saya mahasiswa Teknik Informatika", "channel": "web"},
    )
    assert r_save.status_code == 200
    assert "Teknik Informatika" in r_save.json()["reply"]

    r_mem = client.post("/api/chat", headers=auth_headers(), json={"prompt": "/memori", "channel": "web"})
    assert r_mem.status_code == 200
    assert "Teknik Informatika" in r_mem.json()["reply"]

    r_top = client.post("/api/chat", headers=auth_headers(), json={"prompt": "/top", "channel": "web"})
    assert r_top.status_code == 200
    assert "Aplikasi pemakan RAM terbesar" in r_top.json()["reply"]
