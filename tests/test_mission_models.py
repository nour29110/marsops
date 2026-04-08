"""Tests for marsops.planner.mission — MissionConstraints, MissionGoal, MissionPlan."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from marsops.planner.mission import MissionConstraints, MissionGoal, MissionPlan

# ---------------------------------------------------------------------------
# MissionConstraints
# ---------------------------------------------------------------------------


def test_mission_constraints_defaults() -> None:
    """MissionConstraints uses documented default values."""
    c = MissionConstraints()
    assert c.min_battery_pct == 20.0
    assert c.max_slope_deg == 25.0
    assert c.must_return_to_start is False
    assert c.max_duration_s is None


@pytest.mark.parametrize(
    ("min_bat", "max_slope", "must_return", "max_dur"),
    [
        (30.0, 15.0, True, 3600.0),
        (5.0, 30.0, False, None),
        (0.0, 0.0, True, 0.1),
    ],
)
def test_mission_constraints_custom(
    min_bat: float,
    max_slope: float,
    must_return: bool,
    max_dur: float | None,
) -> None:
    """MissionConstraints stores custom values correctly."""
    c = MissionConstraints(
        min_battery_pct=min_bat,
        max_slope_deg=max_slope,
        must_return_to_start=must_return,
        max_duration_s=max_dur,
    )
    assert c.min_battery_pct == min_bat
    assert c.max_slope_deg == max_slope
    assert c.must_return_to_start == must_return
    assert c.max_duration_s == max_dur


@given(
    min_bat=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    max_slope=st.floats(min_value=0.0, max_value=90.0, allow_nan=False),
)
@settings(max_examples=30)
def test_mission_constraints_hypothesis(min_bat: float, max_slope: float) -> None:
    """MissionConstraints accepts arbitrary valid float ranges."""
    c = MissionConstraints(min_battery_pct=min_bat, max_slope_deg=max_slope)
    assert c.min_battery_pct == min_bat
    assert c.max_slope_deg == max_slope


# ---------------------------------------------------------------------------
# MissionGoal
# ---------------------------------------------------------------------------


def _base_goal() -> MissionGoal:
    return MissionGoal(
        description="survey 3 sites in the north and return",
        start=(5, 5),
        region_of_interest=None,
        min_waypoints=2,
        constraints=MissionConstraints(must_return_to_start=True),
    )


def test_mission_goal_round_trip_model_dump_validate() -> None:
    """MissionGoal survives a model_dump / model_validate round-trip."""
    goal = _base_goal()
    dumped = goal.model_dump()
    restored = MissionGoal.model_validate(dumped)
    assert restored.description == goal.description
    assert restored.start == goal.start
    assert restored.min_waypoints == goal.min_waypoints
    assert restored.constraints.must_return_to_start == goal.constraints.must_return_to_start


def test_mission_goal_round_trip_preserves_roi() -> None:
    """MissionGoal with region_of_interest round-trips correctly."""
    goal = MissionGoal(
        description="explore delta",
        start=(0, 0),
        region_of_interest=(0, 0, 10, 10),
        min_waypoints=1,
    )
    restored = MissionGoal.model_validate(goal.model_dump())
    assert restored.region_of_interest == (0, 0, 10, 10)


def test_mission_goal_defaults() -> None:
    """MissionGoal sets sensible defaults when optional fields are omitted."""
    goal = MissionGoal(description="go somewhere", start=(1, 2))
    assert goal.region_of_interest is None
    assert goal.min_waypoints == 1
    assert isinstance(goal.constraints, MissionConstraints)


@given(
    desc=st.text(min_size=1, max_size=200),
    row=st.integers(min_value=0, max_value=999),
    col=st.integers(min_value=0, max_value=999),
)
@settings(max_examples=30)
def test_mission_goal_hypothesis(desc: str, row: int, col: int) -> None:
    """MissionGoal accepts arbitrary description and start coordinates."""
    goal = MissionGoal(description=desc, start=(row, col))
    assert goal.description == desc
    assert goal.start == (row, col)


# ---------------------------------------------------------------------------
# MissionPlan
# ---------------------------------------------------------------------------


def _make_plan(feasible: bool, description: str = "test mission") -> MissionPlan:
    goal = MissionGoal(description=description, start=(0, 0))
    return MissionPlan(
        goal=goal,
        waypoints=[(1, 1), (2, 2)],
        full_path=[(0, 0), (1, 1), (2, 2)],
        predicted_duration_s=120.0,
        predicted_final_battery_pct=75.5,
        predicted_distance_cells=2,
        feasible=feasible,
        reasoning="test reasoning",
    )


def test_mission_plan_summary_feasible_contains_keyword() -> None:
    """MissionPlan.summary() contains 'FEASIBLE' when feasible=True."""
    plan = _make_plan(feasible=True)
    assert "FEASIBLE" in plan.summary()


def test_mission_plan_summary_infeasible_contains_keyword() -> None:
    """MissionPlan.summary() contains 'INFEASIBLE' when feasible=False."""
    plan = _make_plan(feasible=False)
    assert "INFEASIBLE" in plan.summary()


def test_mission_plan_summary_feasible_not_infeasible() -> None:
    """Feasible plan's summary does not contain 'INFEASIBLE'."""
    plan = _make_plan(feasible=True)
    assert "INFEASIBLE" not in plan.summary()


def test_mission_plan_summary_includes_description() -> None:
    """MissionPlan.summary() includes the mission description string."""
    desc = "unique-survey-description-42"
    plan = _make_plan(feasible=True, description=desc)
    assert desc in plan.summary()


def test_mission_plan_summary_includes_metrics() -> None:
    """MissionPlan.summary() includes duration and battery figures."""
    plan = _make_plan(feasible=True)
    summary = plan.summary()
    assert "120.0" in summary
    assert "75.5" in summary


def test_mission_plan_summary_is_string() -> None:
    """MissionPlan.summary() always returns a non-empty string."""
    for feasible in (True, False):
        plan = _make_plan(feasible=feasible)
        result = plan.summary()
        assert isinstance(result, str)
        assert len(result) > 0


def test_mission_plan_round_trip() -> None:
    """MissionPlan survives a model_dump / model_validate round-trip."""
    plan = _make_plan(feasible=True)
    restored = MissionPlan.model_validate(plan.model_dump())
    assert restored.feasible == plan.feasible
    assert restored.predicted_duration_s == plan.predicted_duration_s
    assert restored.waypoints == plan.waypoints


@pytest.mark.parametrize("feasible", [True, False])
def test_mission_plan_summary_status_line(feasible: bool) -> None:
    """The first line of summary() always starts with '=== MissionPlan ['."""
    plan = _make_plan(feasible=feasible)
    first_line = plan.summary().splitlines()[0]
    assert first_line.startswith("=== MissionPlan [")
