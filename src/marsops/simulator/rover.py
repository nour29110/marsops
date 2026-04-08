"""Mars rover state machine and physics model.

Models a simplified Perseverance-class rover with battery, position, heading,
and clock state.  The rover moves cell-by-cell on a :class:`~marsops.terrain.loader.Terrain`
grid, emitting :class:`~marsops.telemetry.events.TelemetryEvent` records on
each step.
"""

from __future__ import annotations

import logging
import math

from pydantic import BaseModel

from marsops.telemetry.events import TelemetryEvent
from marsops.terrain.loader import Terrain

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class RoverFailure(Exception):  # noqa: N818
    """Raised when the rover cannot continue due to battery exhaustion.

    Attributes:
        message: Human-readable reason for the failure.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class RoverConfig(BaseModel):
    """Physical and operational parameters for the rover.

    Modelled on the Mars 2020 Perseverance rover (see references in each
    field docstring).

    Attributes:
        battery_capacity_wh: Total usable battery capacity in watt-hours.
            Perseverance carries two Li-ion batteries rated at ~2070 Wh total
            (JPL Mars 2020 Rover Fact Sheet, 2020).
        idle_draw_w: Continuous power draw while stationary in watts.
        drive_draw_w: Peak power draw during active driving in watts.
            Set to 120 W as a simplified approximation of Perseverance's
            mobility budget; the MMRTG supplies ~110 W continuously and
            mobility consumes a fraction of that during drive segments
            (a deliberate simplification — not a measured value).
        speed_mps: Top drive speed in metres per second.
            Perseverance's maximum autonavigation speed is ~0.042 m/s
            (JPL Mars 2020 Rover Fact Sheet, 2020).
        drive_efficiency: Duty-cycle fraction representing the fraction of
            travel time the rover is actually moving vs. stopped to image,
            think, or communicate.  A value of 0.5 means the rover drives
            for half of each sol's allocated traverse time.  This is a
            deliberate operational simplification, not a physical efficiency.
        low_battery_threshold_pct: Battery percentage below which the
            low-battery event is emitted.
    """

    battery_capacity_wh: float = 2000.0
    idle_draw_w: float = 50.0
    drive_draw_w: float = 120.0
    speed_mps: float = 0.042
    drive_efficiency: float = 0.5
    low_battery_threshold_pct: float = 20.0


# ---------------------------------------------------------------------------
# Rover
# ---------------------------------------------------------------------------


class Rover:
    """Stateful rover that traverses a terrain grid cell by cell.

    The rover maintains a position, heading, battery level, mission clock, and
    status.  Each call to :meth:`step_to` advances the rover to an adjacent
    cell and returns a :class:`~marsops.telemetry.events.TelemetryEvent`.

    Args:
        terrain: The :class:`~marsops.terrain.loader.Terrain` grid to operate on.
        start: Initial ``(row, col)`` position (must be traversable).
        config: Rover configuration; defaults to :class:`RoverConfig` defaults.

    Raises:
        ValueError: If *start* is not traversable or out of bounds.
    """

    def __init__(
        self,
        terrain: Terrain,
        start: tuple[int, int],
        config: RoverConfig | None = None,
    ) -> None:
        self._terrain = terrain
        self._config = config if config is not None else RoverConfig()

        start_r, start_c = start
        if not terrain.is_traversable(start_r, start_c):
            msg = f"start {start} is not traversable"
            raise ValueError(msg)

        self.position: tuple[int, int] = start
        self.heading_deg: float = 0.0  # 0 = north (up), clockwise
        self.battery_wh: float = self._config.battery_capacity_wh
        self.clock_s: float = 0.0
        self.status: str = "idle"

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> RoverConfig:
        """The rover configuration used at construction.

        Returns:
            The :class:`RoverConfig` instance.
        """
        return self._config

    @property
    def terrain(self) -> Terrain:
        """The terrain grid the rover operates on.

        Returns:
            The :class:`~marsops.terrain.loader.Terrain` instance passed at construction.
        """
        return self._terrain

    @property
    def battery_pct(self) -> float:
        """Current battery state-of-charge as a percentage (0-100).

        Returns:
            Battery percentage clamped to [0, 100].
        """
        pct = 100.0 * self.battery_wh / self._config.battery_capacity_wh
        return max(0.0, min(100.0, pct))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def step_to(self, next_cell: tuple[int, int]) -> TelemetryEvent:
        """Move the rover to an adjacent cell and return a telemetry event.

        The destination must be 8-connected (Chebyshev distance == 1) and
        traversable.  The rover's heading is updated, the mission clock is
        advanced by the travel time, and the battery is drained by the drive
        power for that duration.

        Args:
            next_cell: Target ``(row, col)`` grid coordinate.

        Returns:
            A ``"step"`` :class:`~marsops.telemetry.events.TelemetryEvent`
            describing the move.

        Raises:
            ValueError: If *next_cell* is not 8-adjacent to the current
                position or is not traversable.
            RoverFailure: If executing this step would exhaust the battery
                (energy drops to or below 0 Wh).  The rover status is set
                to ``"failed"`` before the exception is raised.
        """
        cur_r, cur_c = self.position
        nxt_r, nxt_c = next_cell

        # Validate adjacency (Chebyshev distance == 1)
        dr = abs(nxt_r - cur_r)
        dc = abs(nxt_c - cur_c)
        if max(dr, dc) != 1:
            msg = f"{next_cell} is not 8-adjacent to current position {self.position}"
            raise ValueError(msg)

        # Validate traversability
        if not self._terrain.is_traversable(nxt_r, nxt_c):
            msg = f"{next_cell} is not traversable"
            raise ValueError(msg)

        # Euclidean distance in metres
        resolution = self._terrain.metadata.resolution_m
        dist_m = math.sqrt(dr**2 + dc**2) * resolution

        # Travel time and energy; drive_efficiency accounts for the duty cycle
        # (the rover stops frequently to image, think, and communicate).
        travel_s = dist_m / self._config.speed_mps
        energy_wh = self._config.drive_draw_w * travel_s / 3600.0 * self._config.drive_efficiency

        # Battery check
        new_battery = self.battery_wh - energy_wh
        if new_battery <= 0.0:
            self.battery_wh = 0.0
            self.status = "failed"
            msg = f"Battery exhausted moving to {next_cell}"
            raise RoverFailure(msg)

        # Update heading: atan2 gives angle from north, clockwise
        # In grid coords: row increases downward (south), col increases right (east)
        # North = row decreasing = dy < 0 in array coords
        delta_east = float(nxt_c - cur_c)
        delta_south = float(nxt_r - cur_r)
        # heading: 0 = north (up = row decreasing), clockwise
        heading_rad = math.atan2(delta_east, -delta_south)
        self.heading_deg = math.degrees(heading_rad) % 360.0

        # Commit state
        self.battery_wh = new_battery
        self.clock_s += travel_s
        self.position = next_cell
        self.status = "driving"

        elevation = self._terrain.elevation_at(nxt_r, nxt_c)
        return TelemetryEvent(
            timestamp_s=self.clock_s,
            event_type="step",
            position=next_cell,
            battery_pct=self.battery_pct,
            elevation_m=elevation,
            heading_deg=self.heading_deg,
            message=(
                f"Moved to {next_cell} (elev={elevation:.1f} m, hdg={self.heading_deg:.1f} deg)"
            ),
        )
