"""Tests for src/marsops/viz/path_plot.py.

Uses small synthetic Terrain instances.  No real DEM is loaded.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from marsops.telemetry.events import MissionLog, TelemetryEvent
from marsops.terrain.loader import Terrain, TerrainMetadata
from marsops.viz.path_plot import plot_mission_playback, plot_terrain_with_path

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_flat_terrain(rows: int, cols: int, base_elev: float = 0.0) -> Terrain:
    """Return a small flat Terrain for testing."""
    elevation = np.full((rows, cols), base_elev, dtype=np.float32)
    meta = TerrainMetadata(
        name="test",
        source_url="synthetic",
        resolution_m=1.0,
        bounds=(0.0, 0.0, float(cols), float(rows)),
        shape=(rows, cols),
        nodata_value=-9999.0,
    )
    return Terrain(elevation=elevation, metadata=meta)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlotTerrainWithPath:
    """Tests for plot_terrain_with_path."""

    def test_returns_output_path(self, tmp_path: Path) -> None:
        """The function must return the same path it was given."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "test.html"
        result = plot_terrain_with_path(terrain, [(0, 0), (2, 2), (4, 4)], out)
        assert result == out.resolve()

    def test_creates_html_file(self, tmp_path: Path) -> None:
        """An HTML file must exist after the call."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "out.html"
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_html_content_contains_title(self, tmp_path: Path) -> None:
        """The generated HTML must embed the custom title string."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "titled.html"
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], out, title="MyTitle")
        content = out.read_text()
        assert "MyTitle" in content

    def test_empty_path_produces_file(self, tmp_path: Path) -> None:
        """An empty path list must still produce a valid HTML file (heatmap only)."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "empty_path.html"
        result = plot_terrain_with_path(terrain, [], out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories must be created automatically if they do not exist."""
        terrain = make_flat_terrain(5, 5)
        nested_out = tmp_path / "a" / "b" / "c" / "plot.html"
        assert not nested_out.parent.exists()
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], nested_out)
        assert nested_out.exists()

    def test_single_cell_path(self, tmp_path: Path) -> None:
        """A one-cell path (start == goal) must produce a valid file."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "single.html"
        plot_terrain_with_path(terrain, [(2, 2)], out)
        assert out.exists()

    def test_default_title(self, tmp_path: Path) -> None:
        """The default title 'MarsOps Path' must appear in the HTML."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "default_title.html"
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], out)
        content = out.read_text()
        assert "MarsOps Path" in content

    @pytest.mark.parametrize("elev", [-2500.0, 0.0, 1000.0])
    def test_various_elevation_ranges(self, tmp_path: Path, elev: float) -> None:
        """Elevation values at different ranges must not cause errors."""
        terrain = make_flat_terrain(5, 5, base_elev=elev)
        out = tmp_path / f"elev_{int(elev)}.html"
        plot_terrain_with_path(terrain, [(0, 0), (4, 4)], out)
        assert out.exists()


# ---------------------------------------------------------------------------
# Helpers for plot_mission_playback
# ---------------------------------------------------------------------------


def _make_event(
    *,
    timestamp_s: float = 0.0,
    event_type: str = "mission_start",
    position: tuple[int, int] = (0, 0),
    battery_pct: float = 100.0,
    elevation_m: float = 0.0,
    heading_deg: float = 0.0,
    message: str = "test",
) -> TelemetryEvent:
    return TelemetryEvent(
        timestamp_s=timestamp_s,
        event_type=event_type,  # type: ignore[arg-type]
        position=position,
        battery_pct=battery_pct,
        elevation_m=elevation_m,
        heading_deg=heading_deg,
        message=message,
    )


def _minimal_log() -> MissionLog:
    """Two-event log: mission_start then mission_complete."""
    return MissionLog(
        events=[
            _make_event(timestamp_s=0.0, event_type="mission_start", position=(0, 0)),
            _make_event(
                timestamp_s=10.0,
                event_type="mission_complete",
                position=(2, 2),
                battery_pct=80.0,
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Tests for plot_mission_playback
# ---------------------------------------------------------------------------


class TestPlotMissionPlayback:
    """Tests for plot_mission_playback."""

    def test_returns_output_path(self, tmp_path: Path) -> None:
        """The function must return the resolved path it was given."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "playback.html"
        result = plot_mission_playback(terrain, _minimal_log(), out)
        assert result == out.resolve()

    def test_creates_html_file(self, tmp_path: Path) -> None:
        """An HTML file must exist after the call."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "playback.html"
        plot_mission_playback(terrain, _minimal_log(), out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_html_contains_custom_title(self, tmp_path: Path) -> None:
        """The generated HTML must embed the custom title string."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "playback.html"
        plot_mission_playback(terrain, _minimal_log(), out, title="MyPlayback")
        assert "MyPlayback" in out.read_text(encoding="utf-8")

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Parent directories must be created automatically."""
        terrain = make_flat_terrain(5, 5)
        nested = tmp_path / "a" / "b" / "playback.html"
        assert not nested.parent.exists()
        plot_mission_playback(terrain, _minimal_log(), nested)
        assert nested.exists()

    def test_default_title_in_html(self, tmp_path: Path) -> None:
        """The default title 'MarsOps Mission Playback' must appear in the HTML."""
        terrain = make_flat_terrain(5, 5)
        out = tmp_path / "playback.html"
        plot_mission_playback(terrain, _minimal_log(), out)
        assert "MarsOps Mission Playback" in out.read_text(encoding="utf-8")

    def test_multi_event_log_produces_file(self, tmp_path: Path) -> None:
        """A richer log (step + waypoint) produces a valid HTML file."""
        terrain = make_flat_terrain(5, 5)
        log = MissionLog(
            events=[
                _make_event(timestamp_s=0.0, event_type="mission_start", position=(0, 0)),
                _make_event(timestamp_s=5.0, event_type="step", position=(1, 0)),
                _make_event(timestamp_s=10.0, event_type="waypoint_reached", position=(1, 0)),
                _make_event(
                    timestamp_s=20.0,
                    event_type="mission_complete",
                    position=(2, 2),
                    battery_pct=70.0,
                ),
            ]
        )
        out = tmp_path / "rich.html"
        result = plot_mission_playback(terrain, log, out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_single_event_log(self, tmp_path: Path) -> None:
        """A single-event log (mission_start only) produces a valid HTML file."""
        terrain = make_flat_terrain(5, 5)
        log = MissionLog(
            events=[_make_event(timestamp_s=0.0, event_type="mission_start", position=(0, 0))]
        )
        out = tmp_path / "single.html"
        plot_mission_playback(terrain, log, out)
        assert out.exists()

    @pytest.mark.parametrize("elev", [-2500.0, 0.0, 1000.0])
    def test_various_elevation_ranges(self, tmp_path: Path, elev: float) -> None:
        """Elevation values at different ranges must not cause errors."""
        terrain = make_flat_terrain(5, 5, base_elev=elev)
        out = tmp_path / f"pb_elev_{int(elev)}.html"
        plot_mission_playback(terrain, _minimal_log(), out)
        assert out.exists()
