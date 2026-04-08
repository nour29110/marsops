"""Tests for marsops.simulator.anomalies — Anomaly, AnomalyEffect, apply_anomaly.

Covers:
- Anomaly model validation (valid fields, severity range, optional blocked_cells)
- AnomalyEffect default field values
- apply_anomaly for dust_storm: battery drain, forced idle, clock advance
- apply_anomaly for wheel_stuck: blocked_cells propagation, no battery/clock change
- apply_anomaly for thermal_alert: forced idle, clock advance, no direct drain
- Battery clamping: rover.battery_wh never drops below 0
- Hypothesis property-based tests for severity in [0, 1] and beyond
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from marsops.simulator.anomalies import Anomaly, AnomalyEffect, apply_anomaly
from marsops.simulator.rover import Rover, RoverConfig
from marsops.terrain.loader import Terrain, TerrainMetadata

# ---------------------------------------------------------------------------
# Terrain / Rover helpers
# ---------------------------------------------------------------------------


def _flat_terrain(rows: int = 10, cols: int = 10, resolution_m: float = 20.0) -> Terrain:
    """Build a small fully traversable flat terrain (all cells at 10.0 m)."""
    elev = np.full((rows, cols), 10.0, dtype=np.float32)
    meta = TerrainMetadata(
        name="test_flat",
        source_url="test",
        resolution_m=resolution_m,
        bounds=(0.0, 0.0, 1.0, 1.0),
        shape=(rows, cols),
        nodata_value=-9999.0,
    )
    return Terrain(elevation=elev, metadata=meta)


@pytest.fixture()
def flat_terrain() -> Terrain:
    """10x10 flat terrain, all cells traversable."""
    return _flat_terrain()


@pytest.fixture()
def default_config() -> RoverConfig:
    """Default RoverConfig."""
    return RoverConfig()


@pytest.fixture()
def rover_at_2_2(flat_terrain: Terrain, default_config: RoverConfig) -> Rover:
    """Rover at (2, 2) on a 10x10 flat terrain with default config."""
    return Rover(terrain=flat_terrain, start=(2, 2), config=default_config)


# ---------------------------------------------------------------------------
# Anomaly model validation
# ---------------------------------------------------------------------------


class TestAnomalyModel:
    """Validate Anomaly Pydantic model."""

    def test_dust_storm_valid(self) -> None:
        """Anomaly with dust_storm type and severity 0.5 constructs cleanly."""
        a = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.5,
            message="dust storm incoming",
        )
        assert a.anomaly_type == "dust_storm"
        assert a.severity == 0.5
        assert a.blocked_cells is None

    def test_wheel_stuck_with_blocked_cells(self) -> None:
        """Anomaly with wheel_stuck and explicit blocked_cells stores them correctly."""
        cells: set[tuple[int, int]] = {(3, 4), (5, 6)}
        a = Anomaly(
            trigger_at_step=2,
            anomaly_type="wheel_stuck",
            severity=0.0,
            message="wheel stuck",
            blocked_cells=cells,
        )
        assert a.blocked_cells == cells

    def test_thermal_alert_valid(self) -> None:
        """Anomaly with thermal_alert type and severity 1.0 constructs cleanly."""
        a = Anomaly(
            trigger_at_step=5,
            anomaly_type="thermal_alert",
            severity=1.0,
            message="thermal alert",
        )
        assert a.anomaly_type == "thermal_alert"
        assert a.blocked_cells is None

    @pytest.mark.parametrize("severity", [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_severity_range_does_not_raise(self, severity: float) -> None:
        """Anomaly accepts any float severity (Pydantic does not enforce 0-1 range)."""
        a = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=severity,
            message="test",
        )
        assert a.severity == severity

    def test_invalid_anomaly_type_raises(self) -> None:
        """Anomaly with an invalid anomaly_type raises ValidationError."""
        with pytest.raises(ValidationError):
            Anomaly(
                trigger_at_step=0,
                anomaly_type="solar_flare",  # type: ignore[arg-type]
                severity=0.5,
                message="invalid type",
            )

    def test_blocked_cells_optional_default_none(self) -> None:
        """blocked_cells is None by default."""
        a = Anomaly(
            trigger_at_step=0,
            anomaly_type="thermal_alert",
            severity=0.3,
            message="hot",
        )
        assert a.blocked_cells is None

    def test_trigger_at_step_stored(self) -> None:
        """trigger_at_step is stored correctly."""
        a = Anomaly(
            trigger_at_step=7,
            anomaly_type="dust_storm",
            severity=0.1,
            message="step 7 storm",
        )
        assert a.trigger_at_step == 7


# ---------------------------------------------------------------------------
# AnomalyEffect model
# ---------------------------------------------------------------------------


class TestAnomalyEffectModel:
    """Validate AnomalyEffect Pydantic model defaults."""

    def test_defaults(self) -> None:
        """AnomalyEffect defaults: drain=0.0, idle=0.0, blocked=empty set."""
        effect = AnomalyEffect()
        assert effect.battery_drain_pct == 0.0
        assert effect.forced_idle_s == 0.0
        assert effect.new_blocked_cells == set()

    def test_explicit_values(self) -> None:
        """AnomalyEffect stores explicit field values correctly."""
        effect = AnomalyEffect(
            battery_drain_pct=7.5,
            forced_idle_s=1800.0,
            new_blocked_cells={(1, 2)},
        )
        assert effect.battery_drain_pct == 7.5
        assert effect.forced_idle_s == 1800.0
        assert (1, 2) in effect.new_blocked_cells


# ---------------------------------------------------------------------------
# apply_anomaly — dust_storm
# ---------------------------------------------------------------------------


class TestApplyAnomalyDustStorm:
    """Tests for apply_anomaly with anomaly_type='dust_storm'."""

    def test_dust_storm_severity_05_battery_drain_pct(
        self, rover_at_2_2: Rover, default_config: RoverConfig
    ) -> None:
        """dust_storm severity=0.5 produces battery_drain_pct == 7.5."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.5,
            message="storm",
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.battery_drain_pct == pytest.approx(7.5)

    def test_dust_storm_severity_05_forced_idle_s(self, rover_at_2_2: Rover) -> None:
        """dust_storm severity=0.5 produces forced_idle_s == 1800.0."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.5,
            message="storm",
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.forced_idle_s == pytest.approx(1800.0)

    def test_dust_storm_severity_05_no_blocked_cells(self, rover_at_2_2: Rover) -> None:
        """dust_storm produces an empty new_blocked_cells set."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.5,
            message="storm",
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.new_blocked_cells == set()

    def test_dust_storm_severity_05_battery_decreases(
        self, rover_at_2_2: Rover, default_config: RoverConfig
    ) -> None:
        """dust_storm drains rover battery (both direct drain + idle draw)."""
        initial_battery = rover_at_2_2.battery_wh
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.5,
            message="storm",
        )
        apply_anomaly(rover_at_2_2, anomaly)
        assert rover_at_2_2.battery_wh < initial_battery

    def test_dust_storm_severity_05_clock_advances(self, rover_at_2_2: Rover) -> None:
        """dust_storm severity=0.5 advances rover clock by exactly 1800.0 s."""
        initial_clock = rover_at_2_2.clock_s
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.5,
            message="storm",
        )
        apply_anomaly(rover_at_2_2, anomaly)
        assert rover_at_2_2.clock_s == pytest.approx(initial_clock + 1800.0)

    def test_dust_storm_severity_10_drain_pct_15(self, rover_at_2_2: Rover) -> None:
        """dust_storm severity=1.0 gives battery_drain_pct == 15.0."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=1.0,
            message="max storm",
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.battery_drain_pct == pytest.approx(15.0)

    def test_dust_storm_severity_10_forced_idle_3600(self, rover_at_2_2: Rover) -> None:
        """dust_storm severity=1.0 gives forced_idle_s == 3600.0."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=1.0,
            message="max storm",
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.forced_idle_s == pytest.approx(3600.0)

    def test_dust_storm_zero_severity_no_change(self, rover_at_2_2: Rover) -> None:
        """dust_storm severity=0.0 does not change battery or clock."""
        initial_battery = rover_at_2_2.battery_wh
        initial_clock = rover_at_2_2.clock_s
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.0,
            message="no effect",
        )
        apply_anomaly(rover_at_2_2, anomaly)
        assert rover_at_2_2.battery_wh == pytest.approx(initial_battery)
        assert rover_at_2_2.clock_s == pytest.approx(initial_clock)


# ---------------------------------------------------------------------------
# apply_anomaly — wheel_stuck
# ---------------------------------------------------------------------------


class TestApplyAnomalyWheelStuck:
    """Tests for apply_anomaly with anomaly_type='wheel_stuck'."""

    def test_wheel_stuck_blocked_cells_propagated(self, rover_at_2_2: Rover) -> None:
        """wheel_stuck with blocked_cells={(3,4),(5,6)} returns those cells."""
        cells: set[tuple[int, int]] = {(3, 4), (5, 6)}
        anomaly = Anomaly(
            trigger_at_step=2,
            anomaly_type="wheel_stuck",
            severity=0.5,
            message="stuck",
            blocked_cells=cells,
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.new_blocked_cells == {(3, 4), (5, 6)}

    def test_wheel_stuck_battery_drain_zero(self, rover_at_2_2: Rover) -> None:
        """wheel_stuck produces battery_drain_pct == 0.0."""
        anomaly = Anomaly(
            trigger_at_step=2,
            anomaly_type="wheel_stuck",
            severity=0.5,
            message="stuck",
            blocked_cells={(3, 4)},
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.battery_drain_pct == 0.0

    def test_wheel_stuck_forced_idle_zero(self, rover_at_2_2: Rover) -> None:
        """wheel_stuck produces forced_idle_s == 0.0."""
        anomaly = Anomaly(
            trigger_at_step=2,
            anomaly_type="wheel_stuck",
            severity=0.5,
            message="stuck",
            blocked_cells={(3, 4)},
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.forced_idle_s == 0.0

    def test_wheel_stuck_battery_unchanged(self, rover_at_2_2: Rover) -> None:
        """wheel_stuck does not change rover.battery_wh."""
        initial_battery = rover_at_2_2.battery_wh
        anomaly = Anomaly(
            trigger_at_step=2,
            anomaly_type="wheel_stuck",
            severity=0.5,
            message="stuck",
            blocked_cells={(3, 4)},
        )
        apply_anomaly(rover_at_2_2, anomaly)
        assert rover_at_2_2.battery_wh == pytest.approx(initial_battery)

    def test_wheel_stuck_clock_unchanged(self, rover_at_2_2: Rover) -> None:
        """wheel_stuck does not advance rover.clock_s."""
        initial_clock = rover_at_2_2.clock_s
        anomaly = Anomaly(
            trigger_at_step=2,
            anomaly_type="wheel_stuck",
            severity=0.5,
            message="stuck",
            blocked_cells={(3, 4)},
        )
        apply_anomaly(rover_at_2_2, anomaly)
        assert rover_at_2_2.clock_s == pytest.approx(initial_clock)

    def test_wheel_stuck_no_blocked_cells_returns_empty_set(self, rover_at_2_2: Rover) -> None:
        """wheel_stuck with blocked_cells=None returns empty new_blocked_cells."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="wheel_stuck",
            severity=0.0,
            message="stuck no cells",
            blocked_cells=None,
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.new_blocked_cells == set()


# ---------------------------------------------------------------------------
# apply_anomaly — thermal_alert
# ---------------------------------------------------------------------------


class TestApplyAnomalyThermalAlert:
    """Tests for apply_anomaly with anomaly_type='thermal_alert'."""

    def test_thermal_alert_severity_10_forced_idle_7200(self, rover_at_2_2: Rover) -> None:
        """thermal_alert severity=1.0 produces forced_idle_s == 7200.0."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="thermal_alert",
            severity=1.0,
            message="max thermal",
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.forced_idle_s == pytest.approx(7200.0)

    def test_thermal_alert_battery_drain_pct_zero(self, rover_at_2_2: Rover) -> None:
        """thermal_alert produces battery_drain_pct == 0.0."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="thermal_alert",
            severity=1.0,
            message="max thermal",
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.battery_drain_pct == 0.0

    def test_thermal_alert_severity_10_clock_advances_7200(self, rover_at_2_2: Rover) -> None:
        """thermal_alert severity=1.0 advances clock by 7200.0 s."""
        initial_clock = rover_at_2_2.clock_s
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="thermal_alert",
            severity=1.0,
            message="max thermal",
        )
        apply_anomaly(rover_at_2_2, anomaly)
        assert rover_at_2_2.clock_s == pytest.approx(initial_clock + 7200.0)

    def test_thermal_alert_no_blocked_cells(self, rover_at_2_2: Rover) -> None:
        """thermal_alert produces empty new_blocked_cells."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="thermal_alert",
            severity=0.5,
            message="half thermal",
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.new_blocked_cells == set()

    def test_thermal_alert_severity_05_idle_3600(self, rover_at_2_2: Rover) -> None:
        """thermal_alert severity=0.5 gives forced_idle_s == 3600.0."""
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="thermal_alert",
            severity=0.5,
            message="half thermal",
        )
        effect = apply_anomaly(rover_at_2_2, anomaly)
        assert effect.forced_idle_s == pytest.approx(3600.0)

    def test_thermal_alert_drains_idle_power_from_battery(self, rover_at_2_2: Rover) -> None:
        """thermal_alert draws idle power for the forced idle period."""
        initial_battery = rover_at_2_2.battery_wh
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="thermal_alert",
            severity=1.0,
            message="max thermal",
        )
        apply_anomaly(rover_at_2_2, anomaly)
        # idle_draw_w * 7200 s / 3600 = 50 * 2 = 100 Wh drained
        expected_drain_wh = rover_at_2_2.config.idle_draw_w * 7200.0 / 3600.0
        assert rover_at_2_2.battery_wh == pytest.approx(initial_battery - expected_drain_wh)


# ---------------------------------------------------------------------------
# Battery clamping
# ---------------------------------------------------------------------------


class TestBatteryClamping:
    """Battery must never drop below 0 regardless of anomaly severity."""

    def test_dust_storm_near_empty_battery_clamped(self, flat_terrain: Terrain) -> None:
        """dust_storm on a near-empty rover clamps battery_wh to 0, not negative."""
        config = RoverConfig(battery_capacity_wh=2000.0)
        rover = Rover(terrain=flat_terrain, start=(2, 2), config=config)
        # Set battery to almost zero
        rover.battery_wh = 0.5
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=1.0,
            message="drain empty battery",
        )
        apply_anomaly(rover, anomaly)
        assert rover.battery_wh == pytest.approx(0.0)
        assert rover.battery_wh >= 0.0

    def test_thermal_alert_near_empty_battery_clamped(self, flat_terrain: Terrain) -> None:
        """thermal_alert idle drain on near-empty rover clamps battery_wh to 0."""
        rover = Rover(terrain=flat_terrain, start=(2, 2))
        rover.battery_wh = 0.1
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="thermal_alert",
            severity=1.0,
            message="thermal empty battery",
        )
        apply_anomaly(rover, anomaly)
        assert rover.battery_wh >= 0.0

    def test_dust_storm_exactly_zero_battery_stays_zero(self, flat_terrain: Terrain) -> None:
        """dust_storm on a rover with battery_wh=0 keeps it at exactly 0."""
        rover = Rover(terrain=flat_terrain, start=(2, 2))
        rover.battery_wh = 0.0
        anomaly = Anomaly(
            trigger_at_step=0,
            anomaly_type="dust_storm",
            severity=0.8,
            message="already empty",
        )
        apply_anomaly(rover, anomaly)
        assert rover.battery_wh == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------


@given(severity=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=30)
def test_dust_storm_effect_proportional_to_severity(severity: float) -> None:
    """For dust_storm, battery_drain_pct = 15 * severity and forced_idle_s = 3600 * severity."""
    terrain = _flat_terrain()
    rover = Rover(terrain=terrain, start=(2, 2))
    anomaly = Anomaly(
        trigger_at_step=0,
        anomaly_type="dust_storm",
        severity=severity,
        message="hypothesis test",
    )
    effect = apply_anomaly(rover, anomaly)
    assert effect.battery_drain_pct == pytest.approx(15.0 * severity)
    assert effect.forced_idle_s == pytest.approx(3600.0 * severity)


@given(severity=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=30)
def test_thermal_alert_idle_proportional_to_severity(severity: float) -> None:
    """For thermal_alert, forced_idle_s = 7200 * severity and battery_drain_pct = 0."""
    terrain = _flat_terrain()
    rover = Rover(terrain=terrain, start=(2, 2))
    anomaly = Anomaly(
        trigger_at_step=0,
        anomaly_type="thermal_alert",
        severity=severity,
        message="hypothesis thermal",
    )
    effect = apply_anomaly(rover, anomaly)
    assert effect.battery_drain_pct == 0.0
    assert effect.forced_idle_s == pytest.approx(7200.0 * severity)


@given(severity=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=30)
def test_battery_never_negative_hypothesis(severity: float) -> None:
    """apply_anomaly never leaves rover.battery_wh negative for any dust_storm severity."""
    terrain = _flat_terrain()
    rover = Rover(terrain=terrain, start=(2, 2))
    rover.battery_wh = 1.0  # very low battery
    anomaly = Anomaly(
        trigger_at_step=0,
        anomaly_type="dust_storm",
        severity=severity,
        message="clamping hypothesis",
    )
    apply_anomaly(rover, anomaly)
    assert rover.battery_wh >= 0.0


@given(severity=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=30)
def test_wheel_stuck_no_state_mutation_hypothesis(severity: float) -> None:
    """wheel_stuck never mutates rover battery or clock regardless of severity."""
    terrain = _flat_terrain()
    rover = Rover(terrain=terrain, start=(2, 2))
    initial_battery = rover.battery_wh
    initial_clock = rover.clock_s
    anomaly = Anomaly(
        trigger_at_step=0,
        anomaly_type="wheel_stuck",
        severity=severity,
        message="no mutation hypothesis",
        blocked_cells={(1, 1)},
    )
    apply_anomaly(rover, anomaly)
    assert rover.battery_wh == pytest.approx(initial_battery)
    assert rover.clock_s == pytest.approx(initial_clock)
