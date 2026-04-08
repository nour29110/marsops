"""Session state singleton for the MarsOps MCP server.

Holds all mutable per-session objects (terrain, rover, plans, logs, anomalies)
for the lifetime of a single server process.  Thread-safety is not required —
this is a single-process stdio server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from marsops.planner.mission import MissionPlan
from marsops.simulator.anomalies import Anomaly
from marsops.simulator.rover import Rover
from marsops.telemetry.events import MissionLog
from marsops.terrain.loader import Terrain


@dataclass
class SessionState:
    """Mutable session state shared across all MCP tool calls.

    Attributes:
        terrain: Currently loaded :class:`~marsops.terrain.loader.Terrain`, or
            ``None`` if no terrain has been loaded yet.
        terrain_source: Human-readable source string for the loaded terrain
            (``"synthetic"`` or ``"real"``), or ``None``.
        rover: The last :class:`~marsops.simulator.rover.Rover` instance created
            by :func:`execute_mission`, or ``None``.
        last_plan: The most recent :class:`~marsops.planner.mission.MissionPlan`
            produced by :func:`plan_mission`, or ``None``.
        last_log: The most recent :class:`~marsops.telemetry.events.MissionLog`
            produced by :func:`execute_mission`, or ``None``.
        pending_anomalies: Queue of :class:`~marsops.simulator.anomalies.Anomaly`
            objects that will be injected on the next :func:`execute_mission` call.
        last_report_path: Filesystem path of the last written Markdown mission
            report, or ``None`` if no report has been written yet.
    """

    terrain: Terrain | None = None
    terrain_source: str | None = None
    rover: Rover | None = None
    last_plan: MissionPlan | None = None
    last_log: MissionLog | None = None
    pending_anomalies: list[Anomaly] = field(default_factory=list)
    last_report_path: Path | None = None


_SESSION: SessionState = SessionState()


def get_session() -> SessionState:
    """Return the module-level session singleton.

    Returns:
        The single :class:`SessionState` instance for this process.
    """
    return _SESSION


def reset_session() -> None:
    """Reset the session singleton to a clean initial state.

    Intended for use in tests.  Replaces all mutable fields with their
    defaults without replacing the singleton object itself.
    """
    global _SESSION
    _SESSION = SessionState()
