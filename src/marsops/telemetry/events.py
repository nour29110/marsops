"""Telemetry event models for rover mission logging.

Defines the :class:`TelemetryEvent` Pydantic model representing a single
timestamped rover event, and the :class:`MissionLog` container with helpers
for computing mission statistics and persisting events as JSONL.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)

EventType = Literal[
    "step",
    "waypoint_reached",
    "low_battery",
    "mission_start",
    "mission_complete",
    "mission_failed",
]


class TelemetryEvent(BaseModel):
    """A single timestamped rover telemetry event.

    Attributes:
        timestamp_s: Mission elapsed time in seconds at the moment of this event.
        event_type: Categorical label for the event.
        position: Grid position as (row, col) at the moment of this event.
        battery_pct: Battery state-of-charge as a percentage (0-100).
        elevation_m: Terrain elevation in metres at the current position.
        heading_deg: Rover heading in degrees (0 = north/up, clockwise).
        message: Human-readable description of the event.
    """

    timestamp_s: float
    event_type: EventType
    position: tuple[int, int]
    battery_pct: float
    elevation_m: float
    heading_deg: float
    message: str


class MissionLog(BaseModel):
    """Container for an ordered sequence of :class:`TelemetryEvent` records.

    Attributes:
        events: Chronological list of telemetry events for one mission run.
    """

    events: list[TelemetryEvent]

    # ------------------------------------------------------------------
    # Computed statistics
    # ------------------------------------------------------------------

    def duration_s(self) -> float:
        """Return the total mission duration in seconds.

        Computed as the difference between the last and first event timestamps.
        Returns 0.0 if there are fewer than two events.

        Returns:
            Duration in seconds as a float.
        """
        if len(self.events) < 2:
            return 0.0
        return self.events[-1].timestamp_s - self.events[0].timestamp_s

    def distance_cells(self) -> int:
        """Return the total number of cells traversed (step event count).

        Counts the number of ``"step"`` events in the log, which corresponds
        to the number of individual cell-to-cell moves the rover made.

        Returns:
            Integer cell count.
        """
        return sum(1 for e in self.events if e.event_type == "step")

    def waypoints_reached(self) -> int:
        """Return the number of designated waypoints successfully reached.

        Returns:
            Count of ``"waypoint_reached"`` events.
        """
        return sum(1 for e in self.events if e.event_type == "waypoint_reached")

    def final_battery(self) -> float:
        """Return the battery percentage at the end of the mission.

        Uses the last event's battery_pct value.  Returns 100.0 if the log
        is empty.

        Returns:
            Battery percentage as a float.
        """
        if not self.events:
            return 100.0
        return self.events[-1].battery_pct

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_jsonl(self, path: Path) -> None:
        """Write all events to a JSONL file, one JSON object per line.

        Args:
            path: Destination file path.  Parent directories are created
                automatically if they do not exist.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for event in self.events:
                fh.write(event.model_dump_json() + "\n")
        logger.info("MissionLog written to %s (%d events)", path, len(self.events))

    @classmethod
    def from_jsonl(cls, path: Path) -> MissionLog:
        """Load a :class:`MissionLog` from a JSONL file.

        Args:
            path: Source JSONL file.  Each line must be a valid
                :class:`TelemetryEvent` JSON object.

        Returns:
            A populated :class:`MissionLog`.

        Raises:
            FileNotFoundError: If *path* does not exist.
            ValueError: If any line cannot be parsed as a :class:`TelemetryEvent`.
        """
        events: list[TelemetryEvent] = []
        with path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(TelemetryEvent.model_validate(json.loads(line)))
                except Exception as exc:
                    msg = f"Failed to parse line {lineno} of {path}: {exc}"
                    raise ValueError(msg) from exc
        logger.info("MissionLog loaded from %s (%d events)", path, len(events))
        return cls(events=events)
