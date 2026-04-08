"""Tests for marsops.simulator.rover: RoverConfig, Rover, RoverFailure."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marsops.simulator.rover import Rover, RoverConfig, RoverFailure
from marsops.telemetry.events import TelemetryEvent
from marsops.terrain.loader import Terrain, TerrainMetadata

# ---------------------------------------------------------------------------
# Terrain fixture helpers
# ---------------------------------------------------------------------------

_FLAT_ELEVATION = -2600.0
_NODATA_VALUE = -9999.0


def _make_flat_terrain(rows: int = 10, cols: int = 10) -> Terrain:
    """Return a flat 10x10 terrain with all cells at -2600 m."""
    elevation = np.full((rows, cols), _FLAT_ELEVATION, dtype=np.float32)
    meta = TerrainMetadata(
        name="test",
        source_url="test",
        resolution_m=20.0,
        bounds=(0.0, 0.0, 1.0, 1.0),
        shape=(rows, cols),
        nodata_value=_NODATA_VALUE,
    )
    return Terrain(elevation=elevation, metadata=meta)


def _make_terrain_with_nodata(nodata_row: int = 5, nodata_col: int = 5) -> Terrain:
    """Return a 10x10 terrain with one nodata cell."""
    elevation = np.full((10, 10), _FLAT_ELEVATION, dtype=np.float32)
    elevation[nodata_row, nodata_col] = _NODATA_VALUE
    meta = TerrainMetadata(
        name="test",
        source_url="test",
        resolution_m=20.0,
        bounds=(0.0, 0.0, 1.0, 1.0),
        shape=(10, 10),
        nodata_value=_NODATA_VALUE,
    )
    return Terrain(elevation=elevation, metadata=meta)


@pytest.fixture()
def flat_terrain() -> Terrain:
    """10x10 flat terrain at -2600 m."""
    return _make_flat_terrain()


@pytest.fixture()
def default_rover(flat_terrain: Terrain) -> Rover:
    """Rover on flat terrain starting at (0, 0)."""
    return Rover(terrain=flat_terrain, start=(0, 0))


# ---------------------------------------------------------------------------
# RoverConfig defaults
# ---------------------------------------------------------------------------


def test_rover_config_defaults() -> None:
    """RoverConfig has the expected default values."""
    config = RoverConfig()
    assert config.battery_capacity_wh == pytest.approx(2000.0)
    assert config.speed_mps == pytest.approx(0.042)
    assert config.low_battery_threshold_pct == pytest.approx(20.0)


def test_rover_config_custom() -> None:
    """RoverConfig accepts custom values correctly."""
    config = RoverConfig(battery_capacity_wh=500.0, speed_mps=0.1, low_battery_threshold_pct=10.0)
    assert config.battery_capacity_wh == pytest.approx(500.0)
    assert config.speed_mps == pytest.approx(0.1)
    assert config.low_battery_threshold_pct == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Rover construction
# ---------------------------------------------------------------------------


def test_rover_constructs_without_error(flat_terrain: Terrain) -> None:
    """Rover constructs without raising on flat traversable terrain."""
    rover = Rover(terrain=flat_terrain, start=(0, 0))
    assert rover is not None


def test_rover_battery_pct_at_construction(default_rover: Rover) -> None:
    """battery_pct is 100.0 at construction."""
    assert default_rover.battery_pct == pytest.approx(100.0)


def test_rover_initial_position(flat_terrain: Terrain) -> None:
    """Rover starts at the specified position."""
    rover = Rover(terrain=flat_terrain, start=(3, 4))
    assert rover.position == (3, 4)


def test_rover_initial_status(default_rover: Rover) -> None:
    """Rover status is 'idle' at construction."""
    assert default_rover.status == "idle"


def test_rover_raises_on_nodata_start() -> None:
    """Rover raises ValueError when start cell is nodata."""
    terrain = _make_terrain_with_nodata(nodata_row=0, nodata_col=0)
    with pytest.raises(ValueError, match="not traversable"):
        Rover(terrain=terrain, start=(0, 0))


# ---------------------------------------------------------------------------
# step_to: basic move
# ---------------------------------------------------------------------------


def test_step_to_returns_telemetry_event(default_rover: Rover) -> None:
    """step_to on a valid adjacent cell returns a TelemetryEvent with event_type='step'."""
    event = default_rover.step_to((0, 1))
    assert isinstance(event, TelemetryEvent)
    assert event.event_type == "step"


def test_step_to_moves_position(default_rover: Rover) -> None:
    """step_to moves the rover's position to the target cell."""
    default_rover.step_to((0, 1))
    assert default_rover.position == (0, 1)


def test_step_to_advances_clock(default_rover: Rover) -> None:
    """step_to advances the mission clock."""
    initial_clock = default_rover.clock_s
    default_rover.step_to((0, 1))
    assert default_rover.clock_s > initial_clock


def test_step_to_drains_battery(default_rover: Rover) -> None:
    """step_to reduces the battery level."""
    initial_pct = default_rover.battery_pct
    default_rover.step_to((0, 1))
    assert default_rover.battery_pct < initial_pct


# ---------------------------------------------------------------------------
# step_to: validation errors
# ---------------------------------------------------------------------------


def test_step_to_raises_on_non_adjacent_cell(default_rover: Rover) -> None:
    """step_to raises ValueError when target is not 8-adjacent (distance 2 away)."""
    with pytest.raises(ValueError, match="not 8-adjacent"):
        default_rover.step_to((0, 2))


def test_step_to_raises_on_nodata_cell() -> None:
    """step_to raises ValueError when target cell is nodata."""
    terrain = _make_terrain_with_nodata(nodata_row=0, nodata_col=1)
    rover = Rover(terrain=terrain, start=(0, 0))
    with pytest.raises(ValueError, match="not traversable"):
        rover.step_to((0, 1))


@pytest.mark.parametrize(
    "bad_target",
    [
        (3, 1),  # dr=2, dc=0 -> Chebyshev=2
        (1, 3),  # dr=0, dc=2 -> Chebyshev=2
        (3, 3),  # dr=2, dc=2 -> Chebyshev=2
        (1, 1),  # same cell -> Chebyshev=0
        (4, 4),  # far away -> Chebyshev=3
    ],
)
def test_step_to_rejects_non_adjacent_targets(
    flat_terrain: Terrain, bad_target: tuple[int, int]
) -> None:
    """step_to rejects targets that are not exactly 8-adjacent (Chebyshev != 1)."""
    rover = Rover(terrain=flat_terrain, start=(1, 1))
    with pytest.raises(ValueError):
        rover.step_to(bad_target)


# ---------------------------------------------------------------------------
# Battery physics: diagonal vs cardinal drain
# ---------------------------------------------------------------------------


def test_diagonal_drain_sqrt2_times_cardinal() -> None:
    """Diagonal move drains ~sqrt(2) times more than a cardinal move (1% tolerance)."""
    terrain = _make_flat_terrain()

    # Cardinal move: (0,0) -> (0,1)
    rover_cardinal = Rover(terrain=terrain, start=(0, 0))
    initial_wh = rover_cardinal.battery_wh
    rover_cardinal.step_to((0, 1))
    cardinal_drain = initial_wh - rover_cardinal.battery_wh

    # Diagonal move: (0,0) -> (1,1)
    rover_diagonal = Rover(terrain=terrain, start=(0, 0))
    rover_diagonal.step_to((1, 1))
    diagonal_drain = initial_wh - rover_diagonal.battery_wh

    ratio = diagonal_drain / cardinal_drain
    assert ratio == pytest.approx(math.sqrt(2), rel=0.01)


# ---------------------------------------------------------------------------
# Battery exhaustion -> RoverFailure
# ---------------------------------------------------------------------------


def test_battery_exhaustion_raises_rover_failure() -> None:
    """Battery reaching zero raises RoverFailure."""
    config = RoverConfig(battery_capacity_wh=0.001)
    terrain = _make_flat_terrain()
    rover = Rover(terrain=terrain, start=(0, 0), config=config)
    with pytest.raises(RoverFailure):
        rover.step_to((0, 1))


def test_battery_exhaustion_sets_status_failed() -> None:
    """After RoverFailure, rover.status is 'failed'."""
    config = RoverConfig(battery_capacity_wh=0.001)
    terrain = _make_flat_terrain()
    rover = Rover(terrain=terrain, start=(0, 0), config=config)
    with pytest.raises(RoverFailure):
        rover.step_to((0, 1))
    assert rover.status == "failed"


def test_battery_exhaustion_sets_wh_to_zero() -> None:
    """After RoverFailure, battery_wh is 0."""
    config = RoverConfig(battery_capacity_wh=0.001)
    terrain = _make_flat_terrain()
    rover = Rover(terrain=terrain, start=(0, 0), config=config)
    with pytest.raises(RoverFailure):
        rover.step_to((0, 1))
    assert rover.battery_wh == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Heading after step_to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "start, target, expected_heading",
    [
        ((5, 5), (5, 6), 90.0),  # east -> 90 degrees
        ((5, 5), (6, 5), 180.0),  # south -> 180 degrees
        ((5, 5), (4, 5), 0.0),  # north -> 0 degrees
        ((5, 5), (5, 4), 270.0),  # west -> 270 degrees
    ],
)
def test_heading_cardinal_directions(
    flat_terrain: Terrain,
    start: tuple[int, int],
    target: tuple[int, int],
    expected_heading: float,
) -> None:
    """Heading is updated correctly for cardinal moves."""
    rover = Rover(terrain=flat_terrain, start=start)
    rover.step_to(target)
    assert rover.heading_deg == pytest.approx(expected_heading, abs=0.01)


def test_heading_east(flat_terrain: Terrain) -> None:
    """Moving east (col+1, same row) yields heading ~90 degrees."""
    rover = Rover(terrain=flat_terrain, start=(5, 5))
    rover.step_to((5, 6))
    assert rover.heading_deg == pytest.approx(90.0, abs=0.01)


def test_heading_south(flat_terrain: Terrain) -> None:
    """Moving south (row+1, same col) yields heading ~180 degrees."""
    rover = Rover(terrain=flat_terrain, start=(5, 5))
    rover.step_to((6, 5))
    assert rover.heading_deg == pytest.approx(180.0, abs=0.01)


# ---------------------------------------------------------------------------
# battery_pct property clamping
# ---------------------------------------------------------------------------


def test_battery_pct_clamped_to_100(flat_terrain: Terrain) -> None:
    """battery_pct is clamped to 100.0 at construction."""
    rover = Rover(terrain=flat_terrain, start=(0, 0))
    assert rover.battery_pct <= 100.0
    assert rover.battery_pct >= 0.0


# ---------------------------------------------------------------------------
# Hypothesis: sequence of random valid moves keeps non-negative battery and clock
# ---------------------------------------------------------------------------

_DIRECTIONS_8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


@given(
    moves=st.lists(st.sampled_from(_DIRECTIONS_8), min_size=1, max_size=30),
)
@settings(max_examples=100, deadline=800)
def test_hypothesis_battery_and_clock_non_negative(moves: list[tuple[int, int]]) -> None:
    """A sequence of valid 8-connected moves always keeps battery_pct >= 0 and clock_s >= 0."""
    terrain = _make_flat_terrain(rows=10, cols=10)
    # Use a generous battery so we don't exhaust it (stop before threshold)
    config = RoverConfig(battery_capacity_wh=2000.0, low_battery_threshold_pct=20.0)
    rover = Rover(terrain=terrain, start=(4, 4), config=config)

    for dr, dc in moves:
        # Stop if battery is getting low to avoid RoverFailure
        if rover.battery_pct <= config.low_battery_threshold_pct + 5.0:
            break
        row, col = rover.position
        nr, nc = row + dr, col + dc
        if not terrain.is_traversable(nr, nc):
            continue
        try:
            rover.step_to((nr, nc))
        except RoverFailure:
            break

    assert rover.battery_pct >= 0.0
    assert rover.clock_s >= 0.0
