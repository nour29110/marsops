"""FastAPI application for the MarsOps Web API.

Exposes rover mission capabilities as HTTP endpoints and a WebSocket
telemetry stream.  This module is a thin adapter over the same inner
functions used by the MCP server — no business logic is duplicated here.

Run with::

    marsops-web          # via installed console script
    uv run marsops-web   # via uv without activation
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from marsops.mcp_server.server import (
    _execute_mission,
    _get_last_mission_report,
    _get_terrain_info,
    _inject_anomaly,
    _load_terrain,
    _plan_mission_tool,
)
from marsops.mcp_server.state import get_session
from marsops.web_api.events import broadcaster
from marsops.web_api.parser import ParsedCommand, parse_command

logger = logging.getLogger(__name__)

app: FastAPI = FastAPI(title="MarsOps Web API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

_DOWNSAMPLE_THRESHOLD: int = 50


class CommandRequest(BaseModel):
    """HTTP request body for POST /api/command.

    Attributes:
        text: Natural-language command string to parse and dispatch.
        replay_speed_ms: Inter-event delay in milliseconds used when replaying
            mission telemetry through the WebSocket broadcaster after an
            ``execute_mission`` command.  Default 100 ms.
    """

    text: str
    replay_speed_ms: int = 100


class CommandResponse(BaseModel):
    """HTTP response body for POST /api/command.

    Attributes:
        parsed: Structured :class:`~marsops.web_api.parser.ParsedCommand`
            produced by the parser.
        result: Tool output dict, or an empty dict when no tool was dispatched
            (e.g. for ``help`` and ``unknown`` intents).
    """

    parsed: ParsedCommand
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _terrain_payload() -> dict[str, Any] | None:
    """Build a JSON-serialisable terrain payload from the current session.

    Downsamples the elevation grid by a factor of 2 when either dimension
    exceeds :data:`_DOWNSAMPLE_THRESHOLD` to keep HTTP response sizes small.

    Returns:
        A dict with ``shape``, ``elevation``, ``resolution_m``, and ``source``
        keys, or ``None`` if no terrain is currently loaded in the session.
    """
    session = get_session()
    if session.terrain is None:
        return None
    terrain = session.terrain
    elev = terrain.elevation
    rows, cols = terrain.shape
    if rows > _DOWNSAMPLE_THRESHOLD or cols > _DOWNSAMPLE_THRESHOLD:
        elev = elev[::2, ::2]
    return {
        "shape": [rows, cols],
        "elevation": elev.tolist(),
        "resolution_m": terrain.metadata.resolution_m,
        "source": session.terrain_source or "unknown",
    }


async def _execute_mission_async(replay_speed_ms: int) -> dict[str, Any]:
    """Run the mission in a thread then replay telemetry through the broadcaster.

    Executes the synchronous :func:`~marsops.mcp_server.server._execute_mission`
    in a worker thread via :func:`asyncio.to_thread` so it does not block the
    event loop.  After execution completes, iterates the mission log and
    broadcasts each event with an inter-event delay of *replay_speed_ms*
    milliseconds.  The replay finishes before this coroutine returns, so the
    HTTP response is sent only after all telemetry events have been delivered.

    Args:
        replay_speed_ms: Delay between successive broadcast calls, in
            milliseconds.  Pass ``0`` to disable inter-event sleeping.

    Returns:
        The result dict returned by ``_execute_mission``.
    """
    result: dict[str, Any] = await asyncio.to_thread(_execute_mission)
    await _replay_log_to_broadcaster(replay_speed_ms)
    return result


async def _replay_log_to_broadcaster(replay_speed_ms: int) -> None:
    """Replay the last mission log through the telemetry broadcaster.

    Iterates over all events in ``session.last_log`` and broadcasts each one
    as a dict, sleeping *replay_speed_ms* milliseconds between events.
    Sends a sentinel ``{"event_type": "replay_complete"}`` event at the end.

    Args:
        replay_speed_ms: Delay between successive broadcast calls, in
            milliseconds.  Pass ``0`` to disable inter-event sleeping.
    """
    session = get_session()
    if session.last_log is None:
        return
    delay = replay_speed_ms / 1000.0
    for event in session.last_log.events:
        payload = event.model_dump()
        # Tuples are not JSON-serialisable — convert position to a list
        payload["position"] = list(payload["position"])
        await broadcaster.broadcast(payload)
        if delay > 0:
            await asyncio.sleep(delay)
    await broadcaster.broadcast({"event_type": "replay_complete"})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Health-check endpoint.

    Returns:
        A dict with ``status`` (``"ok"``) and ``service`` (``"marsops"``) keys.
    """
    return {"status": "ok", "service": "marsops"}


@app.get("/api/terrain")
async def get_terrain() -> dict[str, Any]:
    """Return the current session terrain as a JSON payload.

    Downsamples grids larger than 50x50 by a factor of 2 before returning
    to keep the HTTP response size manageable.

    Returns:
        200 — dict with ``shape``, ``elevation``, ``resolution_m``, ``source``.
        404 — ``{"detail": "no terrain loaded"}`` when no terrain is in session.
    """
    payload = _terrain_payload()
    if payload is None:
        raise HTTPException(status_code=404, detail="no terrain loaded")
    return payload


@app.post("/api/command", response_model=CommandResponse)
async def post_command(body: CommandRequest) -> CommandResponse:
    """Parse and dispatch a natural-language command.

    Parses ``body.text`` with :func:`~marsops.web_api.parser.parse_command`,
    then dispatches to the appropriate inner function from the MCP server.
    For ``execute_mission``, the mission runs in a worker thread and the full
    telemetry log is replayed through the broadcaster **before** this handler
    returns, so WebSocket clients receive all events prior to the HTTP response.
    Intents ``help`` and ``unknown`` are returned without dispatching any tool.

    Args:
        body: Command request with ``text`` and optional ``replay_speed_ms``.

    Returns:
        :class:`CommandResponse` containing the parsed command and tool result.
    """
    parsed = parse_command(body.text)
    result: dict[str, Any] = {}

    if parsed.intent == "load_terrain":
        source = str(parsed.args.get("source", "synthetic"))
        result = _load_terrain(source=source)

    elif parsed.intent == "get_terrain_info":
        result = _get_terrain_info()

    elif parsed.intent == "plan_mission":
        result = _plan_mission_tool(
            description=str(parsed.args.get("description", "mission")),
            start_row=int(parsed.args["start_row"]),
            start_col=int(parsed.args["start_col"]),
            min_waypoints=int(parsed.args.get("min_waypoints", 2)),
            roi_row_min=parsed.args.get("roi_row_min"),
            roi_col_min=parsed.args.get("roi_col_min"),
            roi_row_max=parsed.args.get("roi_row_max"),
            roi_col_max=parsed.args.get("roi_col_max"),
        )

    elif parsed.intent == "execute_mission":
        result = await _execute_mission_async(body.replay_speed_ms)

    elif parsed.intent == "inject_anomaly":
        result = _inject_anomaly(
            anomaly_type=str(parsed.args["anomaly_type"]),
            trigger_at_step=int(parsed.args["trigger_at_step"]),
            severity=float(parsed.args.get("severity", 0.5)),
            blocked_cells=parsed.args.get("blocked_cells"),
        )

    elif parsed.intent == "get_report":
        result = _get_last_mission_report()

    # help / unknown: no dispatch — return parsed command only

    return CommandResponse(parsed=parsed, result=result)


@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket) -> None:
    """WebSocket endpoint for streaming telemetry events.

    Accepts a WebSocket connection, subscribes to the module-level
    :data:`~marsops.web_api.events.broadcaster`, and forwards every event
    as a JSON message.  Unsubscribes cleanly on disconnect or error.

    Args:
        websocket: The incoming WebSocket connection managed by FastAPI.
    """
    await websocket.accept()
    queue = broadcaster.subscribe()
    logger.info("WebSocket client connected to /ws/telemetry")
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /ws/telemetry")
    finally:
        broadcaster.unsubscribe(queue)


# ---------------------------------------------------------------------------
# Console script entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Start the MarsOps Web API server with Uvicorn.

    Binds to ``0.0.0.0:8000``.  Intended for use as the ``marsops-web``
    console script entry point.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
