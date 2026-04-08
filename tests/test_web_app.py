"""Tests for marsops.web_api.events (TelemetryBroadcaster) and marsops.web_api.app (FastAPI)."""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi.testclient import TestClient

from marsops.mcp_server.state import reset_session
from marsops.web_api.app import app
from marsops.web_api.events import TelemetryBroadcaster

# ---------------------------------------------------------------------------
# Session reset fixture — applied to all tests in this module
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_session():
    reset_session()
    yield
    reset_session()


# ---------------------------------------------------------------------------
# TestClient — module-level (stateless between tests because of clean_session)
# ---------------------------------------------------------------------------

client = TestClient(app)

# ---------------------------------------------------------------------------
# TelemetryBroadcaster unit tests
# ---------------------------------------------------------------------------


def test_subscribe_returns_queue():
    b = TelemetryBroadcaster()
    q = b.subscribe()
    assert q.empty()


def test_subscribe_adds_to_subscriber_list():
    b = TelemetryBroadcaster()
    assert len(b._subscribers) == 0
    b.subscribe()
    assert len(b._subscribers) == 1
    b.subscribe()
    assert len(b._subscribers) == 2


async def _broadcast_helper():
    b = TelemetryBroadcaster()
    q = b.subscribe()
    await b.broadcast({"event_type": "step"})
    return q.get_nowait()


def test_broadcast_delivers_event():
    result = asyncio.run(_broadcast_helper())
    assert result["event_type"] == "step"


def test_unsubscribe_removes_queue():
    b = TelemetryBroadcaster()
    q = b.subscribe()
    b.unsubscribe(q)
    asyncio.run(b.broadcast({"event_type": "step"}))
    assert q.empty()


def test_unsubscribe_reduces_subscriber_count():
    b = TelemetryBroadcaster()
    q = b.subscribe()
    assert len(b._subscribers) == 1
    b.unsubscribe(q)
    assert len(b._subscribers) == 0


def test_unsubscribe_unknown_queue_logs_warning(caplog):
    b = TelemetryBroadcaster()
    q: asyncio.Queue = asyncio.Queue()
    with caplog.at_level(logging.WARNING):
        b.unsubscribe(q)
    assert "unknown queue" in caplog.text


async def _full_queue_helper():
    b = TelemetryBroadcaster()
    q = b.subscribe()
    for _ in range(q.maxsize):
        q.put_nowait({"event_type": "step"})
    # This broadcast should not raise; event is dropped silently
    await b.broadcast({"event_type": "overflow"})


def test_broadcast_drops_when_full():
    asyncio.run(_full_queue_helper())  # must not raise


def test_broadcast_to_multiple_subscribers():
    async def _multi():
        b = TelemetryBroadcaster()
        q1 = b.subscribe()
        q2 = b.subscribe()
        await b.broadcast({"event_type": "ping"})
        return q1.get_nowait(), q2.get_nowait()

    r1, r2 = asyncio.run(_multi())
    assert r1["event_type"] == "ping"
    assert r2["event_type"] == "ping"


def test_broadcast_no_subscribers_does_not_raise():
    async def _empty():
        b = TelemetryBroadcaster()
        await b.broadcast({"event_type": "orphan"})

    asyncio.run(_empty())  # must not raise


# ---------------------------------------------------------------------------
# FastAPI endpoints
# ---------------------------------------------------------------------------


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "marsops"


def test_get_terrain_no_terrain_loaded():
    resp = client.get("/api/terrain")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "no terrain loaded"


def test_post_command_load_terrain():
    resp = client.post("/api/command", json={"text": "load terrain"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"]["intent"] == "load_terrain"
    assert body["result"]["status"] == "ok"
    shape = body["result"]["shape"]
    assert isinstance(shape, list)
    assert len(shape) == 2


def test_get_terrain_after_loading():
    # First load
    load_resp = client.post("/api/command", json={"text": "load terrain"})
    assert load_resp.json()["result"]["status"] == "ok"

    resp = client.get("/api/terrain")
    assert resp.status_code == 200
    body = resp.json()
    assert "shape" in body
    assert "elevation" in body
    assert "resolution_m" in body
    assert "source" in body
    assert isinstance(body["elevation"], list)
    assert all(isinstance(row, list) for row in body["elevation"])
    # shape[0] matches number of rows in elevation (possibly downsampled)
    assert len(body["elevation"]) <= body["shape"][0]


def test_post_command_terrain_info_after_load():
    client.post("/api/command", json={"text": "load terrain"})
    resp = client.post("/api/command", json={"text": "terrain info"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"]["intent"] == "get_terrain_info"
    assert body["result"]["status"] == "ok"


@pytest.mark.parametrize(
    "text",
    [
        "help",
        "xyzzy",
    ],
)
def test_post_command_no_dispatch_for_help_and_unknown(text: str):
    resp = client.post("/api/command", json={"text": text})
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == {}


def test_post_command_plan_mission():
    client.post("/api/command", json={"text": "load terrain"})
    resp = client.post(
        "/api/command",
        json={"text": "plan mission at (10, 20) with 2 waypoints"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"]["intent"] == "plan_mission"
    assert body["result"]["status"] == "ok"
    assert isinstance(body["result"]["waypoints"], list)


def test_post_command_inject_dust_storm():
    resp = client.post("/api/command", json={"text": "inject a dust storm"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"]["intent"] == "inject_anomaly"
    assert body["result"]["status"] == "ok"


@pytest.mark.timeout(30)
def test_post_command_execute_mission_full_chain():
    # Step 1: load terrain
    r1 = client.post("/api/command", json={"text": "load terrain"})
    assert r1.json()["result"]["status"] == "ok"

    # Step 2: plan mission
    r2 = client.post(
        "/api/command",
        json={"text": "plan mission at (10, 20) with 2 waypoints"},
    )
    assert r2.json()["result"]["status"] == "ok"

    # Step 3: execute mission
    r3 = client.post("/api/command", json={"text": "execute mission", "replay_speed_ms": 0})
    assert r3.status_code == 200
    body = r3.json()
    assert body["parsed"]["intent"] == "execute_mission"
    assert body["result"]["status"] == "ok"
    assert body["result"]["outcome"] in ("success", "partial", "failure")


@pytest.mark.timeout(30)
def test_post_command_get_report_after_execute():
    # Chain: load → plan → execute → report
    client.post("/api/command", json={"text": "load terrain"})
    client.post(
        "/api/command",
        json={"text": "plan mission at (10, 20) with 2 waypoints"},
    )
    client.post("/api/command", json={"text": "execute mission", "replay_speed_ms": 0})

    resp = client.post("/api/command", json={"text": "show report"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["status"] == "ok"
    assert isinstance(body["result"]["markdown"], str)
    assert len(body["result"]["markdown"]) > 0


def test_post_command_execute_without_plan_returns_error():
    # Load terrain but do NOT plan
    client.post("/api/command", json={"text": "load terrain"})

    resp = client.post("/api/command", json={"text": "execute mission"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"]["intent"] == "execute_mission"
    assert body["result"]["status"] == "error"


def test_post_command_execute_without_anything_returns_error():
    """Execute with no terrain and no plan must return status=error."""
    resp = client.post("/api/command", json={"text": "execute mission"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["status"] == "error"


def test_command_response_has_parsed_and_result_keys():
    resp = client.post("/api/command", json={"text": "help"})
    body = resp.json()
    assert "parsed" in body
    assert "result" in body


def test_parsed_field_has_intent_and_confidence():
    resp = client.post("/api/command", json={"text": "load terrain"})
    parsed = resp.json()["parsed"]
    assert "intent" in parsed
    assert "confidence" in parsed
    assert parsed["confidence"] == 1.0


def test_unknown_intent_has_clarification_in_parsed():
    resp = client.post("/api/command", json={"text": "frobnicate the rover"})
    parsed = resp.json()["parsed"]
    assert parsed["intent"] == "unknown"
    assert parsed["confidence"] == 0.0
    assert parsed["clarification"] is not None


def test_get_terrain_elevation_is_list_of_lists_after_load():
    client.post("/api/command", json={"text": "load terrain"})
    resp = client.get("/api/terrain")
    body = resp.json()
    elevation = body["elevation"]
    assert isinstance(elevation, list)
    assert len(elevation) > 0
    assert isinstance(elevation[0], list)


def test_get_terrain_source_is_synthetic_after_synthetic_load():
    client.post("/api/command", json={"text": "load terrain"})
    resp = client.get("/api/terrain")
    assert resp.json()["source"] == "synthetic"


def test_get_terrain_resolution_m_is_positive():
    client.post("/api/command", json={"text": "load terrain"})
    resp = client.get("/api/terrain")
    assert resp.json()["resolution_m"] > 0


@pytest.mark.parametrize(
    "text,expected_intent",
    [
        ("run mission", "execute_mission"),
        ("go", "execute_mission"),
        ("terrain info", "get_terrain_info"),
        ("what happened", "get_report"),
    ],
)
def test_various_intents_parsed_correctly(text: str, expected_intent: str):
    resp = client.post("/api/command", json={"text": text})
    assert resp.status_code == 200
    assert resp.json()["parsed"]["intent"] == expected_intent
