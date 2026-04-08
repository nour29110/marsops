"""Tests for marsops.mcp_server.state — SessionState singleton management."""

from __future__ import annotations

import pytest

from marsops.mcp_server.state import SessionState, get_session, reset_session

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_session() -> None:
    """Reset session before each test to ensure isolation."""
    reset_session()


# ---------------------------------------------------------------------------
# SessionState defaults
# ---------------------------------------------------------------------------


class TestSessionStateDefaults:
    """Verify that a freshly constructed SessionState has the correct defaults."""

    def test_terrain_is_none(self) -> None:
        state = SessionState()
        assert state.terrain is None

    def test_terrain_source_is_none(self) -> None:
        state = SessionState()
        assert state.terrain_source is None

    def test_rover_is_none(self) -> None:
        state = SessionState()
        assert state.rover is None

    def test_last_plan_is_none(self) -> None:
        state = SessionState()
        assert state.last_plan is None

    def test_last_log_is_none(self) -> None:
        state = SessionState()
        assert state.last_log is None

    def test_pending_anomalies_is_empty_list(self) -> None:
        state = SessionState()
        assert state.pending_anomalies == []
        assert isinstance(state.pending_anomalies, list)

    def test_last_report_path_is_none(self) -> None:
        state = SessionState()
        assert state.last_report_path is None

    def test_pending_anomalies_are_independent_across_instances(self) -> None:
        """Two SessionState instances must not share the same list object."""
        s1 = SessionState()
        s2 = SessionState()
        s1.pending_anomalies.append("sentinel")  # type: ignore[arg-type]
        assert s2.pending_anomalies == []


# ---------------------------------------------------------------------------
# get_session — singleton behaviour
# ---------------------------------------------------------------------------


class TestGetSession:
    """Verify singleton semantics of get_session()."""

    def test_returns_session_state_instance(self) -> None:
        session = get_session()
        assert isinstance(session, SessionState)

    def test_same_object_on_repeated_calls(self) -> None:
        s1 = get_session()
        s2 = get_session()
        assert s1 is s2

    def test_multiple_calls_return_identical_object(self) -> None:
        sessions = [get_session() for _ in range(5)]
        first = sessions[0]
        for s in sessions[1:]:
            assert s is first

    def test_singleton_reflects_mutations(self) -> None:
        """Mutating the returned object is visible on subsequent calls."""
        get_session().terrain_source = "test_source"
        assert get_session().terrain_source == "test_source"


# ---------------------------------------------------------------------------
# reset_session — resets all fields
# ---------------------------------------------------------------------------


class TestResetSession:
    """Verify that reset_session() restores all fields to their defaults."""

    def test_reset_clears_terrain_source(self) -> None:
        get_session().terrain_source = "synthetic"
        reset_session()
        assert get_session().terrain_source is None

    def test_reset_clears_rover(self) -> None:
        # Assign a sentinel string to rover field to simulate dirty state
        get_session().rover = "fake_rover"  # type: ignore[assignment]
        reset_session()
        assert get_session().rover is None

    def test_reset_clears_last_plan(self) -> None:
        get_session().last_plan = "fake_plan"  # type: ignore[assignment]
        reset_session()
        assert get_session().last_plan is None

    def test_reset_clears_last_log(self) -> None:
        get_session().last_log = "fake_log"  # type: ignore[assignment]
        reset_session()
        assert get_session().last_log is None

    def test_reset_clears_pending_anomalies(self) -> None:
        get_session().pending_anomalies.append("anomaly")  # type: ignore[arg-type]
        reset_session()
        assert get_session().pending_anomalies == []

    def test_reset_clears_last_report_path(self) -> None:
        from pathlib import Path

        get_session().last_report_path = Path("/tmp/report.md")
        reset_session()
        assert get_session().last_report_path is None

    def test_reset_clears_terrain(self) -> None:
        get_session().terrain = "fake_terrain"  # type: ignore[assignment]
        reset_session()
        assert get_session().terrain is None

    def test_reset_returns_fresh_clean_state(self) -> None:
        """After reset, the session must be equal to a brand-new SessionState."""
        session = get_session()
        session.terrain_source = "dirty"
        session.pending_anomalies.append("x")  # type: ignore[arg-type]

        reset_session()
        fresh = get_session()

        assert fresh.terrain is None
        assert fresh.terrain_source is None
        assert fresh.rover is None
        assert fresh.last_plan is None
        assert fresh.last_log is None
        assert fresh.pending_anomalies == []
        assert fresh.last_report_path is None

    def test_get_session_after_reset_is_same_type(self) -> None:
        reset_session()
        assert isinstance(get_session(), SessionState)

    def test_double_reset_leaves_clean_state(self) -> None:
        get_session().terrain_source = "synthetic"
        reset_session()
        reset_session()  # idempotent
        assert get_session().terrain_source is None

    def test_reset_does_not_make_singleton_none(self) -> None:
        """reset_session() must not set the singleton to None — only replace it."""
        reset_session()
        assert get_session() is not None

    def test_pending_anomalies_after_reset_is_new_list(self) -> None:
        """After reset the pending_anomalies list must be a new, empty object."""
        original_list = get_session().pending_anomalies
        original_list.append("x")  # type: ignore[arg-type]
        reset_session()
        new_list = get_session().pending_anomalies
        assert new_list == []
        assert new_list is not original_list
