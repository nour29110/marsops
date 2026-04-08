"""Anomaly injection models and effects for mid-mission failure simulation.

Defines :class:`Anomaly` (an event that fires at a specific path step),
:class:`AnomalyEffect` (the resulting state changes), and :func:`apply_anomaly`
which applies the effect directly to a :class:`~marsops.simulator.rover.Rover`.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from marsops.simulator.rover import Rover

logger = logging.getLogger(__name__)


class Anomaly(BaseModel):
    """A mid-mission anomaly that fires at a specific path step.

    Attributes:
        trigger_at_step: Zero-indexed path step at which this anomaly fires.
            Step 0 fires before the first move (path[0] -> path[1]).
        anomaly_type: Category of anomaly.  One of ``"dust_storm"``,
            ``"wheel_stuck"``, or ``"thermal_alert"``.
        severity: Fractional severity from 0.0 (minimal) to 1.0 (catastrophic).
        message: Human-readable description of the anomaly event.
        blocked_cells: Optional set of ``(row, col)`` cells that become
            impassable.  Only meaningful for ``"wheel_stuck"`` anomalies;
            ignored otherwise.
    """

    trigger_at_step: int
    anomaly_type: Literal["dust_storm", "wheel_stuck", "thermal_alert"]
    severity: float  # 0.0-1.0
    message: str
    blocked_cells: set[tuple[int, int]] | None = None


class AnomalyEffect(BaseModel):
    """The quantified effect of a fired anomaly on rover state.

    Attributes:
        battery_drain_pct: Percentage of total battery capacity drained
            as a direct result of this anomaly (before idle draw is computed).
        forced_idle_s: Seconds of forced idle time added to the mission clock.
            Idle power draw is also deducted from the battery for this period.
        new_blocked_cells: Cells that became impassable as a result of the
            anomaly.  Only populated for ``"wheel_stuck"`` anomalies.
    """

    battery_drain_pct: float = 0.0
    forced_idle_s: float = 0.0
    new_blocked_cells: set[tuple[int, int]] = Field(default_factory=set)


def apply_anomaly(rover: Rover, anomaly: Anomaly) -> AnomalyEffect:
    """Apply an anomaly's effect to the rover and return the resulting effect.

    Deterministic mapping from anomaly type to effect:

    * ``"dust_storm"``: Drains battery by ``15 * severity``% of total capacity
      and imposes ``3600 * severity`` seconds of forced idle (during which idle
      power continues to draw).
    * ``"wheel_stuck"``: No battery or time penalty; returns
      ``anomaly.blocked_cells`` (or an empty set) as newly impassable cells.
      The caller (engine) is responsible for triggering rerouting.
    * ``"thermal_alert"``: Imposes ``7200 * severity`` seconds of forced idle
      (rover must cool down before driving resumes).

    Battery drain is clamped so ``rover.battery_wh`` never drops below 0.
    Forced idle time advances ``rover.clock_s`` and draws idle power
    (``rover.config.idle_draw_w``) for the full idle period.

    Args:
        rover: The live :class:`~marsops.simulator.rover.Rover` instance whose
            state will be mutated in-place.
        anomaly: The :class:`Anomaly` to apply.

    Returns:
        An :class:`AnomalyEffect` describing what changed so the engine can
        decide whether recovery is required.
    """
    battery_drain_pct = 0.0
    forced_idle_s = 0.0
    new_blocked_cells: set[tuple[int, int]] = set()

    if anomaly.anomaly_type == "dust_storm":
        battery_drain_pct = 15.0 * anomaly.severity
        forced_idle_s = 3600.0 * anomaly.severity

    elif anomaly.anomaly_type == "wheel_stuck":
        new_blocked_cells = set(anomaly.blocked_cells) if anomaly.blocked_cells else set()

    elif anomaly.anomaly_type == "thermal_alert":
        forced_idle_s = 7200.0 * anomaly.severity

    # Apply direct battery drain (percentage of total capacity)
    if battery_drain_pct > 0.0:
        drain_wh = battery_drain_pct / 100.0 * rover.config.battery_capacity_wh
        rover.battery_wh = max(0.0, rover.battery_wh - drain_wh)

    # Apply forced idle: advance clock and drain idle power for the idle period
    if forced_idle_s > 0.0:
        idle_drain_wh = rover.config.idle_draw_w * forced_idle_s / 3600.0
        rover.battery_wh = max(0.0, rover.battery_wh - idle_drain_wh)
        rover.clock_s += forced_idle_s

    logger.warning(
        "Anomaly fired: type=%s severity=%.2f pos=%s battery=%.1f%% "
        "drain_pct=%.1f idle_s=%.1f blocked_cells=%d",
        anomaly.anomaly_type,
        anomaly.severity,
        rover.position,
        rover.battery_pct,
        battery_drain_pct,
        forced_idle_s,
        len(new_blocked_cells),
    )

    return AnomalyEffect(
        battery_drain_pct=battery_drain_pct,
        forced_idle_s=forced_idle_s,
        new_blocked_cells=new_blocked_cells,
    )
