"""Tests for marsops.planner.dry_run — dry_run_mission and evaluate_plan."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marsops.planner.dry_run import dry_run_mission, evaluate_plan
from marsops.planner.mission import MissionConstraints
from marsops.simulator.rover import RoverConfig
from marsops.terrain.loader import Terrain, TerrainMetadata

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _flat_terrain(rows: int = 20, cols: int = 20) -> Terrain:
    """Build a small flat traversable terrain for testing."""
    elev = np.full((rows, cols), -2600.0, dtype=np.float32)
    meta = TerrainMetadata(
        name="test",
        source_url="test",
        resolution_m=20.0,
        bounds=(0.0, 0.0, 1.0, 1.0),
        shape=(rows, cols),
        nodata_value=-9999.0,
    )
    return Terrain(elevation=elev, metadata=meta)


def _blocked_terrain() -> Terrain:
    """Build a terrain where cell (5,5) and its neighbours are nodata (unreachable)."""
    elev = np.full((10, 10), -2600.0, dtype=np.float32)
    # Surround (5,5) with nodata to make it unreachable from (0,0)
    for r in range(4, 7):
        for c in range(4, 7):
            elev[r, c] = -9999.0
    # The target itself is nodata too — fully isolated
    elev[5, 5] = -9999.0
    meta = TerrainMetadata(
        name="blocked",
        source_url="test",
        resolution_m=20.0,
        bounds=(0.0, 0.0, 1.0, 1.0),
        shape=(10, 10),
        nodata_value=-9999.0,
    )
    return Terrain(elevation=elev, metadata=meta)


@pytest.fixture()
def flat20() -> Terrain:
    """20x20 flat terrain fixture."""
    return _flat_terrain(20, 20)


@pytest.fixture()
def default_config() -> RoverConfig:
    """Default rover configuration fixture."""
    return RoverConfig()


# ---------------------------------------------------------------------------
# dry_run_mission
# ---------------------------------------------------------------------------


def test_dry_run_single_waypoint_returns_valid_tuple(
    flat20: Terrain, default_config: RoverConfig
) -> None:
    """dry_run_mission with 1 reachable waypoint returns positive duration/battery/cells."""
    start = (2, 2)
    waypoints = [(15, 15)]
    path, duration, battery, cells = dry_run_mission(flat20, start, waypoints, default_config)

    assert isinstance(path, list)
    assert len(path) > 0
    assert duration > 0.0
    assert battery > 0.0
    assert cells > 0


def test_dry_run_empty_waypoints_trivial_path(flat20: Terrain) -> None:
    """dry_run_mission with empty waypoints returns ([start], 0.0, 100.0, 0)."""
    start = (5, 5)
    path, duration, battery, cells = dry_run_mission(flat20, start, [])

    assert path == [start]
    assert duration == 0.0
    assert battery == 100.0
    assert cells == 0


def test_dry_run_same_cell_waypoint(flat20: Terrain, default_config: RoverConfig) -> None:
    """dry_run_mission where start == waypoint skips the segment gracefully."""
    start = (3, 3)
    waypoints = [(3, 3)]  # Same cell as start
    path, duration, battery, cells = dry_run_mission(flat20, start, waypoints, default_config)

    # The function skips equal consecutive stops; only start remains in path
    assert path == [start]
    assert duration == 0.0
    assert battery == 100.0
    assert cells == 0


def test_dry_run_unreachable_waypoint_no_exception() -> None:
    """dry_run_mission with a nodata-blocked waypoint returns battery=-1 without raising."""
    terrain = _blocked_terrain()
    start = (0, 0)
    # (5,5) is in the middle of a nodata block — A* cannot reach it
    waypoints = [(5, 5)]

    path, _duration, battery, _cells = dry_run_mission(terrain, start, waypoints)

    # No exception must be raised; battery < 0 signals failure
    assert isinstance(path, list)
    assert battery == -1.0


def test_dry_run_returns_4_tuple(flat20: Terrain) -> None:
    """dry_run_mission always returns a 4-tuple."""
    result = dry_run_mission(flat20, (0, 0), [(10, 10)])
    assert len(result) == 4


def test_dry_run_multiple_waypoints(flat20: Terrain, default_config: RoverConfig) -> None:
    """dry_run_mission with multiple waypoints concatenates path segments correctly."""
    start = (0, 0)
    waypoints = [(5, 5), (10, 10), (15, 15)]
    path, duration, battery, cells = dry_run_mission(flat20, start, waypoints, default_config)

    assert path[0] == start
    assert duration > 0.0
    assert battery > 0.0
    assert cells > 0


def test_dry_run_default_config_used_when_none(flat20: Terrain) -> None:
    """dry_run_mission with rover_config=None uses default RoverConfig."""
    start = (1, 1)
    waypoints = [(10, 10)]
    _path, duration, battery, _cells = dry_run_mission(flat20, start, waypoints, None)

    assert battery > 0.0
    assert duration > 0.0


def test_dry_run_energy_hungry_rover_exhausts(flat20: Terrain) -> None:
    """dry_run_mission with an extreme rover config may exhaust battery (battery < 0)."""
    bad_config = RoverConfig(battery_capacity_wh=1.0, drive_draw_w=100_000.0)
    start = (0, 0)
    waypoints = [(19, 19)]  # Far away on a 20x20 grid
    _path, _duration, battery, _cells = dry_run_mission(flat20, start, waypoints, bad_config)

    # Either succeeds or fails with battery signal <= 0; no exception raised.
    assert isinstance(battery, float)


# ---------------------------------------------------------------------------
# evaluate_plan
# ---------------------------------------------------------------------------


def _make_plan_data(
    battery: float,
    duration: float = 100.0,
    cells: int = 10,
) -> tuple[list[tuple[int, int]], float, float, int]:
    path: list[tuple[int, int]] = [(0, 0), (1, 1)]
    return (path, duration, battery, cells)


@pytest.mark.parametrize(
    ("battery", "duration", "max_dur", "expected_feasible"),
    [
        # Nominal: battery above min, no duration limit
        (80.0, 100.0, None, True),
        # Battery exactly at min (20.0) — should be feasible (not below)
        (20.0, 100.0, None, True),
        # Battery below min — infeasible
        (19.9, 100.0, None, False),
        # Battery signal negative — A* failure
        (-1.0, 0.0, None, False),
        # Duration exceeds max_duration_s — infeasible
        (80.0, 5000.0, 3600.0, False),
        # Duration within limit — feasible
        (80.0, 3600.0, 7200.0, True),
        # Duration exactly at limit — feasible (<=, not <)
        (80.0, 3600.0, 3600.0, True),
    ],
)
def test_evaluate_plan_parametrized(
    battery: float,
    duration: float,
    max_dur: float | None,
    expected_feasible: bool,
) -> None:
    """evaluate_plan correctly classifies all constraint branches."""
    constraints = MissionConstraints(
        min_battery_pct=20.0,
        max_duration_s=max_dur,
    )
    plan_data = _make_plan_data(battery=battery, duration=duration)
    feasible, reason = evaluate_plan(plan_data, constraints)

    assert feasible == expected_feasible
    assert isinstance(reason, str)
    assert len(reason) > 0


def test_evaluate_plan_feasible_reason_contains_battery() -> None:
    """evaluate_plan feasible reason mentions battery percentage."""
    constraints = MissionConstraints(min_battery_pct=20.0)
    plan_data = _make_plan_data(battery=75.3)
    feasible, reason = evaluate_plan(plan_data, constraints)

    assert feasible is True
    assert "battery" in reason.lower() or "75.3" in reason


def test_evaluate_plan_infeasible_battery_reason_mentions_min() -> None:
    """evaluate_plan infeasible reason mentions the minimum battery threshold."""
    constraints = MissionConstraints(min_battery_pct=30.0)
    plan_data = _make_plan_data(battery=10.0)
    feasible, reason = evaluate_plan(plan_data, constraints)

    assert feasible is False
    assert "30.0" in reason or "minimum" in reason.lower()


def test_evaluate_plan_astar_failure_signal() -> None:
    """evaluate_plan returns (False, ...) when battery is negative (A* failure)."""
    constraints = MissionConstraints()
    plan_data = _make_plan_data(battery=-1.0, duration=0.0)
    feasible, reason = evaluate_plan(plan_data, constraints)

    assert feasible is False
    assert "path" in reason.lower() or "battery" in reason.lower()


def test_evaluate_plan_duration_exceeded_reason() -> None:
    """evaluate_plan infeasible reason mentions duration when cap exceeded."""
    constraints = MissionConstraints(max_duration_s=1000.0)
    plan_data = _make_plan_data(battery=90.0, duration=2000.0)
    feasible, reason = evaluate_plan(plan_data, constraints)

    assert feasible is False
    assert "2000.0" in reason or "duration" in reason.lower()


def test_evaluate_plan_no_duration_constraint() -> None:
    """evaluate_plan ignores duration when max_duration_s is None."""
    constraints = MissionConstraints(min_battery_pct=10.0, max_duration_s=None)
    # Very long duration but no cap
    plan_data = _make_plan_data(battery=50.0, duration=999_999.0)
    feasible, _reason = evaluate_plan(plan_data, constraints)

    assert feasible is True


@given(
    battery=st.floats(min_value=20.0, max_value=100.0, allow_nan=False),
    duration=st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False),
)
@settings(max_examples=30)
def test_evaluate_plan_feasible_hypothesis(battery: float, duration: float) -> None:
    """evaluate_plan is feasible when battery >= 20 and no duration cap."""
    constraints = MissionConstraints(min_battery_pct=20.0, max_duration_s=None)
    plan_data = _make_plan_data(battery=battery, duration=duration)
    feasible, _reason = evaluate_plan(plan_data, constraints)
    assert feasible is True
