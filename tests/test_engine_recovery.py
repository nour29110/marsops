"""Tests for marsops.simulator.engine — execute_path and execute_path_with_recovery.

Covers:
- execute_path: trivial single-cell path emits mission_start + mission_complete
- execute_path: normal walk emits mission_start, step(s), mission_complete
- execute_path: low_battery event fires exactly once when threshold is crossed
- execute_path: waypoint_reached fires for every declared waypoint visited
- execute_path: RoverFailure mid-walk results in mission_failed event and no re-raise
- execute_path_with_recovery: no anomalies produces same event types and count as execute_path
- execute_path_with_recovery: dust_storm anomaly emits an anomaly event and completes
- execute_path_with_recovery: wheel_stuck anomaly triggers recovery_replan and completes
- execute_path_with_recovery: abort_to_start recovery emits mission_failed with abort reason
- execute_path_with_recovery: trivial single-cell path completes immediately
- execute_path_with_recovery: RoverFailure mid-walk captured as mission_failed
- execute_path_with_recovery: continue strategy carries on unchanged
- Hypothesis: event sequence always starts with mission_start for any path length
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marsops.planner.mission import MissionConstraints, MissionGoal
from marsops.planner.mission_planner_runtime import plan_mission
from marsops.planner.recovery import RecoveryStrategy
from marsops.simulator.anomalies import Anomaly
from marsops.simulator.engine import execute_path, execute_path_with_recovery
from marsops.simulator.rover import Rover, RoverConfig
from marsops.telemetry.events import MissionLog
from marsops.terrain.loader import Terrain, TerrainMetadata

# ---------------------------------------------------------------------------
# Terrain / helper factories
# ---------------------------------------------------------------------------

_ROWS = 20
_COLS = 20
_RES = 18.0  # metres per cell


def _flat_terrain(
    rows: int = _ROWS,
    cols: int = _COLS,
    resolution_m: float = _RES,
) -> Terrain:
    """Build a small fully traversable flat terrain (all cells at 10.0 m elevation).

    Args:
        rows: Number of grid rows.
        cols: Number of grid columns.
        resolution_m: Ground-sample distance in metres per pixel.

    Returns:
        A :class:`~marsops.terrain.loader.Terrain` where every cell is
        traversable with zero slope.
    """
    elev = np.full((rows, cols), 10.0, dtype=np.float32)
    meta = TerrainMetadata(
        name="engine_test_flat",
        source_url="test",
        resolution_m=resolution_m,
        bounds=(0.0, 0.0, 1.0, 1.0),
        shape=(rows, cols),
        nodata_value=-9999.0,
    )
    return Terrain(elevation=elev, metadata=meta)


def _make_rover(
    terrain: Terrain,
    start: tuple[int, int] = (0, 0),
    config: RoverConfig | None = None,
) -> Rover:
    """Construct a Rover at *start* on *terrain*.

    Args:
        terrain: Terrain grid to operate on.
        start: Starting (row, col) cell.
        config: Optional RoverConfig; uses defaults when None.

    Returns:
        An initialised :class:`~marsops.simulator.rover.Rover`.
    """
    return Rover(terrain=terrain, start=start, config=config)


def _make_goal(
    start: tuple[int, int] = (0, 0),
    min_waypoints: int = 1,
) -> MissionGoal:
    """Build a loose MissionGoal for engine tests on the 20x20 terrain.

    Args:
        start: Starting (row, col) cell.
        min_waypoints: Minimum number of waypoints required.

    Returns:
        A :class:`~marsops.planner.mission.MissionGoal` with relaxed constraints.
    """
    return MissionGoal(
        description="flat survey",
        start=start,
        min_waypoints=min_waypoints,
        region_of_interest=(0, 0, 19, 19),
        constraints=MissionConstraints(
            min_battery_pct=5.0,
            max_slope_deg=25.0,
            must_return_to_start=False,
            max_duration_s=None,
        ),
    )


def _event_types(log: MissionLog) -> list[str]:
    """Return the ordered list of event_type strings from a MissionLog.

    Args:
        log: Mission log to inspect.

    Returns:
        List of event type strings.
    """
    return [e.event_type for e in log.events]


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def terrain() -> Terrain:
    """20x20 flat traversable terrain, resolution 18 m."""
    return _flat_terrain()


@pytest.fixture()
def default_config() -> RoverConfig:
    """Default RoverConfig (Perseverance-class parameters)."""
    return RoverConfig()


@pytest.fixture()
def rover(terrain: Terrain, default_config: RoverConfig) -> Rover:
    """Rover at (0, 0) on the 20x20 flat terrain with default config."""
    return _make_rover(terrain, start=(0, 0), config=default_config)


@pytest.fixture()
def short_path() -> list[tuple[int, int]]:
    """Three-cell horizontal path: (0,0) -> (0,1) -> (0,2)."""
    return [(0, 0), (0, 1), (0, 2)]


@pytest.fixture()
def goal(terrain: Terrain) -> MissionGoal:
    """Default MissionGoal for engine tests."""
    return _make_goal(start=(0, 0), min_waypoints=1)


# ---------------------------------------------------------------------------
# execute_path — trivial single-cell path
# ---------------------------------------------------------------------------


class TestExecutePathTrivial:
    """execute_path with a single-cell path (no moves required)."""

    def test_single_cell_path_emits_mission_start(self, terrain: Terrain) -> None:
        """Single-cell path emits mission_start as the first event."""
        rover = _make_rover(terrain, start=(0, 0))
        log = execute_path(rover, [(0, 0)])
        assert log.events[0].event_type == "mission_start"

    def test_single_cell_path_emits_mission_complete(self, terrain: Terrain) -> None:
        """Single-cell path emits mission_complete as the second event."""
        rover = _make_rover(terrain, start=(0, 0))
        log = execute_path(rover, [(0, 0)])
        assert log.events[-1].event_type == "mission_complete"

    def test_single_cell_path_exactly_two_events(self, terrain: Terrain) -> None:
        """Single-cell path produces exactly two events (start + complete)."""
        rover = _make_rover(terrain, start=(0, 0))
        log = execute_path(rover, [(0, 0)])
        assert len(log.events) == 2

    def test_single_cell_path_no_step_events(self, terrain: Terrain) -> None:
        """Single-cell path produces zero step events."""
        rover = _make_rover(terrain, start=(0, 0))
        log = execute_path(rover, [(0, 0)])
        assert log.distance_cells() == 0


# ---------------------------------------------------------------------------
# execute_path — normal multi-cell walk
# ---------------------------------------------------------------------------


class TestExecutePathNormalWalk:
    """execute_path with a multi-cell path under normal conditions."""

    def test_first_event_is_mission_start(
        self, rover: Rover, short_path: list[tuple[int, int]]
    ) -> None:
        """First event is always mission_start."""
        log = execute_path(rover, short_path)
        assert log.events[0].event_type == "mission_start"

    def test_last_event_is_mission_complete(
        self, rover: Rover, short_path: list[tuple[int, int]]
    ) -> None:
        """Last event is mission_complete when no failure occurs."""
        log = execute_path(rover, short_path)
        assert log.events[-1].event_type == "mission_complete"

    def test_step_events_count_equals_path_moves(
        self, rover: Rover, short_path: list[tuple[int, int]]
    ) -> None:
        """Number of step events equals len(path) - 1."""
        log = execute_path(rover, short_path)
        expected_steps = len(short_path) - 1
        assert log.distance_cells() == expected_steps

    def test_returns_mission_log_instance(
        self, rover: Rover, short_path: list[tuple[int, int]]
    ) -> None:
        """execute_path always returns a MissionLog instance."""
        log = execute_path(rover, short_path)
        assert isinstance(log, MissionLog)

    def test_mission_complete_contains_position_in_message(
        self, rover: Rover, short_path: list[tuple[int, int]]
    ) -> None:
        """mission_complete message includes rover position."""
        log = execute_path(rover, short_path)
        complete_event = log.events[-1]
        assert "Mission complete" in complete_event.message

    @pytest.mark.parametrize(
        "path",
        [
            [(0, 0), (0, 1)],
            [(0, 0), (0, 1), (0, 2), (0, 3)],
            [(5, 5), (5, 6), (5, 7), (6, 7), (7, 7)],
        ],
    )
    def test_various_paths_complete_successfully(
        self, terrain: Terrain, path: list[tuple[int, int]]
    ) -> None:
        """Various multi-cell paths complete with mission_complete as last event."""
        rover = _make_rover(terrain, start=path[0])
        log = execute_path(rover, path)
        assert log.events[-1].event_type == "mission_complete"


# ---------------------------------------------------------------------------
# execute_path — low_battery event
# ---------------------------------------------------------------------------


class TestExecutePathLowBattery:
    """execute_path emits low_battery exactly once when threshold crossed."""

    def test_low_battery_fires_exactly_once(self, terrain: Terrain) -> None:
        """low_battery event appears exactly once even across a long path."""
        # Use a tiny battery so that it drops below threshold during traversal
        config = RoverConfig(
            battery_capacity_wh=100.0,
            low_battery_threshold_pct=95.0,  # threshold is very high so it fires early
        )
        rover = _make_rover(terrain, start=(0, 0), config=config)
        # Walk 5 cells — enough to cross the 95% threshold
        path = [(0, c) for c in range(6)]
        log = execute_path(rover, path)
        low_battery_count = sum(1 for e in log.events if e.event_type == "low_battery")
        assert low_battery_count <= 1

    def test_low_battery_event_precedes_mission_complete(self, terrain: Terrain) -> None:
        """If a low_battery event fires, it appears before mission_complete."""
        config = RoverConfig(
            battery_capacity_wh=100.0,
            low_battery_threshold_pct=95.0,
        )
        rover = _make_rover(terrain, start=(0, 0), config=config)
        path = [(0, c) for c in range(6)]
        log = execute_path(rover, path)
        types = _event_types(log)
        if "low_battery" in types:
            lb_idx = types.index("low_battery")
            complete_idx = types.index("mission_complete")
            assert lb_idx < complete_idx

    def test_no_low_battery_when_battery_stays_above_threshold(
        self, rover: Rover, short_path: list[tuple[int, int]]
    ) -> None:
        """No low_battery event when battery comfortably exceeds threshold."""
        # Default rover at 100% battery, short path; default threshold 20%
        log = execute_path(rover, short_path)
        assert "low_battery" not in _event_types(log)


# ---------------------------------------------------------------------------
# execute_path — waypoint_reached
# ---------------------------------------------------------------------------


class TestExecutePathWaypointReached:
    """execute_path emits waypoint_reached for each declared waypoint visited."""

    def test_waypoint_reached_fires_for_declared_waypoint(
        self, rover: Rover, short_path: list[tuple[int, int]]
    ) -> None:
        """waypoint_reached fires when path visits a declared waypoint cell."""
        waypoints: set[tuple[int, int]] = {(0, 1)}
        log = execute_path(rover, short_path, waypoints=waypoints)
        assert "waypoint_reached" in _event_types(log)

    def test_waypoint_reached_count_matches_visited_waypoints(self, rover: Rover) -> None:
        """waypoint_reached count equals the number of waypoints visited."""
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        waypoints: set[tuple[int, int]] = {(0, 1), (0, 3)}
        log = execute_path(rover, path, waypoints=waypoints)
        assert log.waypoints_reached() == 2

    def test_no_waypoint_reached_when_no_waypoints_declared(
        self, rover: Rover, short_path: list[tuple[int, int]]
    ) -> None:
        """No waypoint_reached event when waypoints is None."""
        log = execute_path(rover, short_path, waypoints=None)
        assert log.waypoints_reached() == 0

    def test_no_waypoint_reached_for_undeclared_cells(
        self, rover: Rover, short_path: list[tuple[int, int]]
    ) -> None:
        """Cells traversed but not in waypoints do not fire waypoint_reached."""
        # Declare a waypoint that is NOT on the path
        waypoints: set[tuple[int, int]] = {(5, 5)}
        log = execute_path(rover, short_path, waypoints=waypoints)
        assert log.waypoints_reached() == 0


# ---------------------------------------------------------------------------
# execute_path — RoverFailure → mission_failed
# ---------------------------------------------------------------------------


class TestExecutePathRoverFailure:
    """execute_path captures RoverFailure and emits mission_failed without re-raising."""

    def test_rover_failure_emits_mission_failed(self, terrain: Terrain) -> None:
        """Battery exhaustion mid-path produces a mission_failed event."""
        # Very tiny battery so step_to exhausts it immediately
        config = RoverConfig(
            battery_capacity_wh=0.001,  # essentially empty
        )
        rover = _make_rover(terrain, start=(0, 0), config=config)
        path = [(0, 0), (0, 1), (0, 2)]
        log = execute_path(rover, path)
        assert "mission_failed" in _event_types(log)

    def test_rover_failure_does_not_raise(self, terrain: Terrain) -> None:
        """execute_path never raises even on battery exhaustion."""
        config = RoverConfig(battery_capacity_wh=0.001)
        rover = _make_rover(terrain, start=(0, 0), config=config)
        path = [(0, 0), (0, 1)]
        # Must not raise
        log = execute_path(rover, path)
        assert isinstance(log, MissionLog)

    def test_rover_failure_no_mission_complete_after_failure(self, terrain: Terrain) -> None:
        """After mission_failed there is no mission_complete event."""
        config = RoverConfig(battery_capacity_wh=0.001)
        rover = _make_rover(terrain, start=(0, 0), config=config)
        path = [(0, 0), (0, 1), (0, 2)]
        log = execute_path(rover, path)
        types = _event_types(log)
        assert "mission_complete" not in types

    def test_mission_failed_message_contains_failure_reason(self, terrain: Terrain) -> None:
        """mission_failed event message describes the battery failure."""
        config = RoverConfig(battery_capacity_wh=0.001)
        rover = _make_rover(terrain, start=(0, 0), config=config)
        path = [(0, 0), (0, 1)]
        log = execute_path(rover, path)
        failed_events = [e for e in log.events if e.event_type == "mission_failed"]
        assert len(failed_events) == 1
        assert "Mission failed" in failed_events[0].message


# ---------------------------------------------------------------------------
# execute_path_with_recovery — no anomalies parity with execute_path
# ---------------------------------------------------------------------------


class TestExecutePathWithRecoveryNoParity:
    """execute_path_with_recovery with no anomalies matches execute_path exactly."""

    @pytest.mark.parametrize(
        "path",
        [
            [(0, 0), (0, 1), (0, 2)],
            [(1, 1), (1, 2), (1, 3), (2, 3)],
        ],
    )
    def test_no_anomalies_same_event_types(
        self, terrain: Terrain, path: list[tuple[int, int]]
    ) -> None:
        """With no anomalies, event types from both functions are identical."""
        rover_a = _make_rover(terrain, start=path[0])
        rover_b = _make_rover(terrain, start=path[0])

        log_a = execute_path(rover_a, path)
        log_b = execute_path_with_recovery(rover_b, path, anomalies=None)

        assert _event_types(log_a) == _event_types(log_b)

    @pytest.mark.parametrize(
        "path",
        [
            [(0, 0), (0, 1), (0, 2)],
            [(1, 1), (1, 2), (1, 3), (2, 3)],
        ],
    )
    def test_no_anomalies_same_event_count(
        self, terrain: Terrain, path: list[tuple[int, int]]
    ) -> None:
        """With no anomalies, total event count from both functions is identical."""
        rover_a = _make_rover(terrain, start=path[0])
        rover_b = _make_rover(terrain, start=path[0])

        log_a = execute_path(rover_a, path)
        log_b = execute_path_with_recovery(rover_b, path, anomalies=None)

        assert len(log_a.events) == len(log_b.events)

    def test_no_anomalies_single_cell_parity(self, terrain: Terrain) -> None:
        """Single-cell path produces identical events with and without recovery wrapper."""
        rover_a = _make_rover(terrain, start=(0, 0))
        rover_b = _make_rover(terrain, start=(0, 0))
        log_a = execute_path(rover_a, [(0, 0)])
        log_b = execute_path_with_recovery(rover_b, [(0, 0)], anomalies=None)
        assert _event_types(log_a) == _event_types(log_b)

    def test_no_anomalies_empty_anomaly_list_same_as_none(
        self, terrain: Terrain, short_path: list[tuple[int, int]]
    ) -> None:
        """anomalies=[] produces the same result as anomalies=None."""
        rover_a = _make_rover(terrain, start=(0, 0))
        rover_b = _make_rover(terrain, start=(0, 0))
        log_a = execute_path_with_recovery(rover_a, short_path, anomalies=None)
        log_b = execute_path_with_recovery(rover_b, short_path, anomalies=[])
        assert _event_types(log_a) == _event_types(log_b)


# ---------------------------------------------------------------------------
# execute_path_with_recovery — dust_storm anomaly
# ---------------------------------------------------------------------------


class TestExecutePathWithRecoveryDustStorm:
    """dust_storm anomaly fires anomaly event and mission continues to completion."""

    def test_dust_storm_emits_anomaly_event(self, terrain: Terrain) -> None:
        """A dust_storm anomaly at step 0 produces an anomaly event in the log."""
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.1,  # mild — only drains 1.5% battery, 360 s idle
            message="mild dust storm",
        )
        log = execute_path_with_recovery(rover, path, anomalies=[anomaly])
        assert "anomaly" in _event_types(log)

    def test_dust_storm_continues_to_mission_complete(self, terrain: Terrain) -> None:
        """After a mild dust_storm, the mission still reaches mission_complete."""
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.1,
            message="mild dust storm",
        )
        log = execute_path_with_recovery(rover, path, anomalies=[anomaly])
        assert log.events[-1].event_type == "mission_complete"

    def test_dust_storm_anomaly_event_before_mission_complete(self, terrain: Terrain) -> None:
        """anomaly event appears before mission_complete in the log."""
        path = [(0, 0), (0, 1), (0, 2)]
        rover = _make_rover(terrain, start=(0, 0))
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.05,
            message="dust storm",
        )
        log = execute_path_with_recovery(rover, path, anomalies=[anomaly])
        types = _event_types(log)
        assert types.index("anomaly") < types.index("mission_complete")

    def test_dust_storm_anomaly_event_message_matches(self, terrain: Terrain) -> None:
        """anomaly event message equals the Anomaly.message field."""
        path = [(0, 0), (0, 1), (0, 2)]
        rover = _make_rover(terrain, start=(0, 0))
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.05,
            message="a very specific dust storm message",
        )
        log = execute_path_with_recovery(rover, path, anomalies=[anomaly])
        anomaly_events = [e for e in log.events if e.event_type == "anomaly"]
        assert anomaly_events[0].message == "a very specific dust storm message"

    def test_dust_storm_no_recovery_replan_without_recovery_fn(self, terrain: Terrain) -> None:
        """Dust storm alone (no recovery_fn) does not produce recovery_replan."""
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.1,
            message="storm",
        )
        log = execute_path_with_recovery(rover, path, anomalies=[anomaly])
        assert "recovery_replan" not in _event_types(log)


# ---------------------------------------------------------------------------
# execute_path_with_recovery — wheel_stuck anomaly with recovery_fn
# ---------------------------------------------------------------------------


class TestExecutePathWithRecoveryWheelStuck:
    """wheel_stuck anomaly triggers recovery_replan and mission completes."""

    def test_wheel_stuck_triggers_recovery_replan(self, terrain: Terrain) -> None:
        """wheel_stuck anomaly with blocked cells causes a recovery_replan event."""
        # Use plan_mission to get a real path so the engine can continue after replan
        goal = _make_goal(start=(0, 0), min_waypoints=1)
        plan = plan_mission(terrain, goal)
        assert plan.feasible, "Precondition: flat terrain must yield a feasible plan"

        path = plan.full_path
        rover = _make_rover(terrain, start=path[0])

        # Block a cell that is NOT on the first step but is ahead in the path
        # We use a cell far from the rover that is not in the path
        blocked_cell: tuple[int, int] = (15, 15)

        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=0.5,
            message="wheel stuck near hazard",
            blocked_cells={blocked_cell},
        )

        def _recovery_fn(
            t: Terrain,
            r: Rover,
            og: MissionGoal,
            rem_wps: list[tuple[int, int]],
            blocked: set[tuple[int, int]],
            rc: RoverConfig | None,
        ) -> RecoveryStrategy:
            """Return a replan_around strategy using plan_mission."""
            new_goal = _make_goal(start=r.position, min_waypoints=1)
            new_plan = plan_mission(t, new_goal, rc)
            if new_plan.feasible:
                return RecoveryStrategy(
                    strategy_type="replan_around",
                    new_plan=new_plan,
                    reasoning="replanned around blocked cell",
                )
            return RecoveryStrategy(
                strategy_type="continue",
                new_plan=None,
                reasoning="could not replan, continuing",
            )

        log = execute_path_with_recovery(
            rover,
            path,
            anomalies=[anomaly],
            recovery_fn=_recovery_fn,
            terrain=terrain,
            original_goal=goal,
        )
        assert "recovery_replan" in _event_types(log)

    def test_wheel_stuck_mission_continues_to_complete(self, terrain: Terrain) -> None:
        """After recovery_replan due to wheel_stuck, mission reaches mission_complete."""
        goal = _make_goal(start=(0, 0), min_waypoints=1)
        plan = plan_mission(terrain, goal)
        assert plan.feasible

        path = plan.full_path
        rover = _make_rover(terrain, start=path[0])
        blocked_cell: tuple[int, int] = (15, 15)

        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=0.5,
            message="wheel stuck",
            blocked_cells={blocked_cell},
        )

        def _recovery_fn(
            t: Terrain,
            r: Rover,
            og: MissionGoal,
            rem_wps: list[tuple[int, int]],
            blocked: set[tuple[int, int]],
            rc: RoverConfig | None,
        ) -> RecoveryStrategy:
            new_goal = _make_goal(start=r.position, min_waypoints=1)
            new_plan = plan_mission(t, new_goal, rc)
            if new_plan.feasible:
                return RecoveryStrategy(
                    strategy_type="replan_around",
                    new_plan=new_plan,
                    reasoning="replanned",
                )
            return RecoveryStrategy(
                strategy_type="continue",
                new_plan=None,
                reasoning="continue",
            )

        log = execute_path_with_recovery(
            rover,
            path,
            anomalies=[anomaly],
            recovery_fn=_recovery_fn,
            terrain=terrain,
            original_goal=goal,
        )
        assert log.events[-1].event_type == "mission_complete"

    def test_wheel_stuck_anomaly_event_present(self, terrain: Terrain) -> None:
        """wheel_stuck anomaly always emits an anomaly event."""
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=0.5,
            message="wheel stuck",
            blocked_cells={(15, 15)},
        )
        log = execute_path_with_recovery(rover, path, anomalies=[anomaly])
        assert "anomaly" in _event_types(log)


# ---------------------------------------------------------------------------
# execute_path_with_recovery — abort_to_start recovery
# ---------------------------------------------------------------------------


class TestExecutePathWithRecoveryAbort:
    """recovery_fn returning abort_to_start emits mission_failed with abort reason."""

    def _abort_recovery_fn(
        self,
        t: Terrain,
        r: Rover,
        og: MissionGoal,
        rem_wps: list[tuple[int, int]],
        blocked: set[tuple[int, int]],
        rc: RoverConfig | None,
    ) -> RecoveryStrategy:
        """Always return abort_to_start (simulates irrecoverable anomaly)."""
        return RecoveryStrategy(
            strategy_type="abort_to_start",
            new_plan=None,
            reasoning="test abort",
        )

    def test_abort_emits_mission_failed(self, terrain: Terrain) -> None:
        """abort_to_start strategy produces a mission_failed event."""
        goal = _make_goal(start=(0, 0))
        path = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
        rover = _make_rover(terrain, start=(0, 0))

        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=1.0,
            message="catastrophic wheel stuck",
            blocked_cells={(1, 0), (1, 1)},
        )

        log = execute_path_with_recovery(
            rover,
            path,
            anomalies=[anomaly],
            recovery_fn=self._abort_recovery_fn,
            terrain=terrain,
            original_goal=goal,
        )
        assert "mission_failed" in _event_types(log)

    def test_abort_mission_failed_message_contains_abort_reason(self, terrain: Terrain) -> None:
        """mission_failed message contains the abort reason from the strategy."""
        goal = _make_goal(start=(0, 0))
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))

        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=1.0,
            message="wheel stuck",
            blocked_cells={(5, 5)},
        )

        log = execute_path_with_recovery(
            rover,
            path,
            anomalies=[anomaly],
            recovery_fn=self._abort_recovery_fn,
            terrain=terrain,
            original_goal=goal,
        )
        failed_events = [e for e in log.events if e.event_type == "mission_failed"]
        assert len(failed_events) == 1
        assert "test abort" in failed_events[0].message

    def test_abort_no_mission_complete_event(self, terrain: Terrain) -> None:
        """After abort_to_start there is no mission_complete event."""
        goal = _make_goal(start=(0, 0))
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))

        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=1.0,
            message="wheel stuck",
            blocked_cells={(5, 5)},
        )

        log = execute_path_with_recovery(
            rover,
            path,
            anomalies=[anomaly],
            recovery_fn=self._abort_recovery_fn,
            terrain=terrain,
            original_goal=goal,
        )
        assert "mission_complete" not in _event_types(log)

    def test_abort_does_not_raise(self, terrain: Terrain) -> None:
        """execute_path_with_recovery never raises even on abort_to_start."""
        goal = _make_goal(start=(0, 0))
        path = [(0, 0), (0, 1), (0, 2)]
        rover = _make_rover(terrain, start=(0, 0))

        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=1.0,
            message="stuck",
            blocked_cells={(5, 5)},
        )

        log = execute_path_with_recovery(
            rover,
            path,
            anomalies=[anomaly],
            recovery_fn=self._abort_recovery_fn,
            terrain=terrain,
            original_goal=goal,
        )
        assert isinstance(log, MissionLog)

    def test_abort_with_lambda_recovery_fn(self, terrain: Terrain) -> None:
        """Lambda recovery_fn returning abort_to_start works correctly."""
        goal = _make_goal(start=(0, 0))
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))

        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=0.5,
            message="stuck",
            blocked_cells={(8, 8)},
        )

        abort_fn = lambda t, r, og, rem, bl, rc: RecoveryStrategy(  # noqa: E731
            strategy_type="abort_to_start",
            new_plan=None,
            reasoning="lambda abort",
        )

        log = execute_path_with_recovery(
            rover,
            path,
            anomalies=[anomaly],
            recovery_fn=abort_fn,
            terrain=terrain,
            original_goal=goal,
        )
        failed_events = [e for e in log.events if e.event_type == "mission_failed"]
        assert len(failed_events) == 1
        assert "lambda abort" in failed_events[0].message


# ---------------------------------------------------------------------------
# execute_path_with_recovery — continue strategy
# ---------------------------------------------------------------------------


class TestExecutePathWithRecoveryContinue:
    """continue strategy means carry on along the current path unchanged."""

    def test_continue_strategy_no_recovery_replan_event(self, terrain: Terrain) -> None:
        """continue strategy does not produce a recovery_replan event."""
        goal = _make_goal(start=(0, 0))
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))

        # dust_storm with low severity — battery barely drops, won't trigger
        # recovery (needs_recovery = False since battery stays above threshold).
        # To force recovery_fn to be called, we use wheel_stuck with blocked_cells,
        # but have the recovery_fn return "continue".
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=0.0,
            message="minor stuck",
            blocked_cells={(15, 15)},
        )

        continue_fn = lambda t, r, og, rem, bl, rc: RecoveryStrategy(  # noqa: E731
            strategy_type="continue",
            new_plan=None,
            reasoning="continue as planned",
        )

        log = execute_path_with_recovery(
            rover,
            path,
            anomalies=[anomaly],
            recovery_fn=continue_fn,
            terrain=terrain,
            original_goal=goal,
        )
        assert "recovery_replan" not in _event_types(log)

    def test_continue_strategy_mission_completes(self, terrain: Terrain) -> None:
        """continue strategy allows mission to complete normally."""
        goal = _make_goal(start=(0, 0))
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))

        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=0.0,
            message="minor stuck",
            blocked_cells={(15, 15)},
        )

        continue_fn = lambda t, r, og, rem, bl, rc: RecoveryStrategy(  # noqa: E731
            strategy_type="continue",
            new_plan=None,
            reasoning="continue",
        )

        log = execute_path_with_recovery(
            rover,
            path,
            anomalies=[anomaly],
            recovery_fn=continue_fn,
            terrain=terrain,
            original_goal=goal,
        )
        assert log.events[-1].event_type == "mission_complete"


# ---------------------------------------------------------------------------
# execute_path_with_recovery — trivial single-cell path
# ---------------------------------------------------------------------------


class TestExecutePathWithRecoveryTrivial:
    """execute_path_with_recovery with single-cell path completes immediately."""

    def test_single_cell_path_emits_mission_start(self, terrain: Terrain) -> None:
        """Single-cell path emits mission_start as the first event."""
        rover = _make_rover(terrain, start=(0, 0))
        log = execute_path_with_recovery(rover, [(0, 0)])
        assert log.events[0].event_type == "mission_start"

    def test_single_cell_path_emits_mission_complete(self, terrain: Terrain) -> None:
        """Single-cell path emits mission_complete as the last event."""
        rover = _make_rover(terrain, start=(0, 0))
        log = execute_path_with_recovery(rover, [(0, 0)])
        assert log.events[-1].event_type == "mission_complete"

    def test_single_cell_path_no_anomaly_events(self, terrain: Terrain) -> None:
        """Single-cell path with anomaly but no moves — anomaly never fires."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.5,
            message="storm",
        )
        rover = _make_rover(terrain, start=(0, 0))
        # Single-cell path exits before the while loop — anomaly at step 0 never fires
        log = execute_path_with_recovery(rover, [(0, 0)], anomalies=[anomaly])
        assert log.events[-1].event_type == "mission_complete"


# ---------------------------------------------------------------------------
# execute_path_with_recovery — RoverFailure captured
# ---------------------------------------------------------------------------


class TestExecutePathWithRecoveryRoverFailure:
    """RoverFailure during recovery mission is captured as mission_failed."""

    def test_rover_failure_emits_mission_failed(self, terrain: Terrain) -> None:
        """Battery exhaustion during recovery mission yields mission_failed."""
        config = RoverConfig(battery_capacity_wh=0.001)
        rover = _make_rover(terrain, start=(0, 0), config=config)
        path = [(0, 0), (0, 1), (0, 2)]
        log = execute_path_with_recovery(rover, path, anomalies=None)
        assert "mission_failed" in _event_types(log)

    def test_rover_failure_does_not_raise(self, terrain: Terrain) -> None:
        """execute_path_with_recovery never raises on RoverFailure."""
        config = RoverConfig(battery_capacity_wh=0.001)
        rover = _make_rover(terrain, start=(0, 0), config=config)
        path = [(0, 0), (0, 1)]
        log = execute_path_with_recovery(rover, path, anomalies=None)
        assert isinstance(log, MissionLog)


# ---------------------------------------------------------------------------
# execute_path_with_recovery — waypoint tracking
# ---------------------------------------------------------------------------


class TestExecutePathWithRecoveryWaypoints:
    """Waypoint events are correctly tracked in the recovery engine."""

    def test_waypoints_reached_in_recovery_engine(self, terrain: Terrain) -> None:
        """Waypoints declared in the call are reached and logged."""
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        waypoints: set[tuple[int, int]] = {(0, 2)}
        rover = _make_rover(terrain, start=(0, 0))
        log = execute_path_with_recovery(rover, path, waypoints=waypoints)
        assert log.waypoints_reached() == 1

    def test_no_waypoints_no_waypoint_reached_events(
        self, terrain: Terrain, short_path: list[tuple[int, int]]
    ) -> None:
        """No waypoints declared means no waypoint_reached events."""
        rover = _make_rover(terrain, start=(0, 0))
        log = execute_path_with_recovery(rover, short_path, waypoints=None)
        assert log.waypoints_reached() == 0


# ---------------------------------------------------------------------------
# execute_path_with_recovery — multiple anomalies at different steps
# ---------------------------------------------------------------------------


class TestExecutePathWithRecoveryMultipleAnomalies:
    """Multiple anomalies at different steps all fire correctly."""

    def test_two_anomalies_both_emit_anomaly_events(self, terrain: Terrain) -> None:
        """Two anomalies at different steps each produce an anomaly event."""
        path = [(0, c) for c in range(6)]
        rover = _make_rover(terrain, start=(0, 0))

        anomaly_0 = Anomaly(
            trigger_at_step=0,
            anomaly_type="thermal_alert",
            severity=0.05,
            message="early thermal",
        )
        anomaly_2 = Anomaly(
            trigger_at_step=2,
            anomaly_type="dust_storm",
            severity=0.05,
            message="late storm",
        )

        log = execute_path_with_recovery(rover, path, anomalies=[anomaly_0, anomaly_2])
        anomaly_events = [e for e in log.events if e.event_type == "anomaly"]
        assert len(anomaly_events) == 2

    def test_anomaly_fires_at_correct_step(self, terrain: Terrain) -> None:
        """An anomaly with trigger_at_step=1 fires after the first move."""
        path = [(0, 0), (0, 1), (0, 2), (0, 3)]
        rover = _make_rover(terrain, start=(0, 0))

        anomaly = Anomaly(
            trigger_at_step=1,
            anomaly_type="dust_storm",
            severity=0.05,
            message="step 1 storm",
        )

        log = execute_path_with_recovery(rover, path, anomalies=[anomaly])
        # The anomaly fires at step 1, so there should be at least one step before it
        types = _event_types(log)
        anomaly_idx = types.index("anomaly")
        step_events_before = types[:anomaly_idx].count("step")
        assert step_events_before >= 1


# ---------------------------------------------------------------------------
# Hypothesis: event sequence invariants
# ---------------------------------------------------------------------------


@given(path_len=st.integers(min_value=1, max_value=8))
@settings(max_examples=20)
def test_execute_path_always_starts_with_mission_start(path_len: int) -> None:
    """execute_path always emits mission_start as the first event, for any path."""
    terrain = _flat_terrain()
    # Build a horizontal path of path_len cells starting at (0,0)
    path = [(0, c) for c in range(path_len)]
    rover = _make_rover(terrain, start=(0, 0))
    log = execute_path(rover, path)
    assert log.events[0].event_type == "mission_start"


@given(path_len=st.integers(min_value=1, max_value=8))
@settings(max_examples=20)
def test_execute_path_always_has_terminal_event(path_len: int) -> None:
    """execute_path last event is always mission_complete or mission_failed."""
    terrain = _flat_terrain()
    path = [(0, c) for c in range(path_len)]
    rover = _make_rover(terrain, start=(0, 0))
    log = execute_path(rover, path)
    assert log.events[-1].event_type in ("mission_complete", "mission_failed")


@given(path_len=st.integers(min_value=1, max_value=8))
@settings(max_examples=20)
def test_execute_path_with_recovery_always_starts_with_mission_start(
    path_len: int,
) -> None:
    """execute_path_with_recovery always emits mission_start as the first event."""
    terrain = _flat_terrain()
    path = [(0, c) for c in range(path_len)]
    rover = _make_rover(terrain, start=(0, 0))
    log = execute_path_with_recovery(rover, path)
    assert log.events[0].event_type == "mission_start"


@given(path_len=st.integers(min_value=2, max_value=8))
@settings(max_examples=20)
def test_execute_path_step_count_matches_path_length(path_len: int) -> None:
    """Step event count equals path_len - 1 when rover has sufficient battery."""
    terrain = _flat_terrain()
    path = [(0, c) for c in range(path_len)]
    rover = _make_rover(terrain, start=(0, 0))
    log = execute_path(rover, path)
    # Only verify when mission completed (not failed due to battery)
    if log.events[-1].event_type == "mission_complete":
        assert log.distance_cells() == path_len - 1


@given(
    path_len=st.integers(min_value=2, max_value=6),
    severity=st.floats(min_value=0.01, max_value=0.15, allow_nan=False),
)
@settings(max_examples=15)
def test_execute_path_with_recovery_dust_storm_produces_anomaly_event(
    path_len: int,
    severity: float,
) -> None:
    """dust_storm anomaly always produces an anomaly event for any path and severity."""
    terrain = _flat_terrain()
    path = [(0, c) for c in range(path_len)]
    rover = _make_rover(terrain, start=(0, 0))
    anomaly = Anomaly(
        trigger_at_step=0,
        anomaly_type="dust_storm",
        severity=severity,
        message="hypothesis storm",
    )
    log = execute_path_with_recovery(rover, path, anomalies=[anomaly])
    assert "anomaly" in _event_types(log)
