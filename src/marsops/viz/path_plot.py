"""Terrain visualisation with planned rover path overlay.

Renders a Plotly figure combining a terrain elevation heatmap with a
planned path drawn as a cyan scatter line.  The figure is saved as a
self-contained HTML file for interactive exploration.

Note:
    Visualization for this module was written directly because the
    ``viz-builder`` sub-agent does not yet exist in this project.  When
    ``viz-builder`` is created, this module should be reviewed and any
    future viz work delegated to that agent.
"""

from __future__ import annotations

import logging
from pathlib import Path

import plotly.graph_objects as go

from marsops.terrain.loader import Terrain

logger = logging.getLogger(__name__)


def plot_terrain_with_path(
    terrain: Terrain,
    path: list[tuple[int, int]],
    output_path: Path,
    title: str = "MarsOps Path",
) -> Path:
    """Render a terrain heatmap with a rover path overlay and save as HTML.

    Produces an interactive Plotly figure containing:

    * A :class:`~plotly.graph_objects.Heatmap` of the elevation grid using
      the ``"YlOrBr"`` colourscale (yellow-orange-brown, classic Mars palette).
    * A :class:`~plotly.graph_objects.Scatter` line tracing the planned
      *path* in cyan, with a green circle marker at the start and a red
      square marker at the goal.
    * Hover text showing the elevation at each grid cell.

    The figure is written to *output_path* as a standalone HTML file via
    :meth:`plotly.graph_objects.Figure.write_html`.

    Args:
        terrain: Elevation grid to visualise.
        path: Ordered list of ``(row, col)`` coordinates produced by
            :func:`~marsops.planner.astar.astar`.
        output_path: Destination ``.html`` file path.  Parent directories
            are created automatically if they do not exist.
        title: Plot title displayed at the top of the figure.

    Returns:
        The resolved *output_path* after the file has been written.
    """
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    elevation = terrain.elevation

    # Build hover text matrix: elevation at each cell
    rows, cols = terrain.shape
    hover_text: list[list[str]] = [
        [f"elev: {elevation[r, c]:.1f} m" for c in range(cols)] for r in range(rows)
    ]

    heatmap = go.Heatmap(
        z=elevation.tolist(),
        colorscale="YlOrBr",
        colorbar={"title": "Elevation (m)"},
        text=hover_text,
        hovertemplate="row=%{y}, col=%{x}<br>%{text}<extra></extra>",
        showscale=True,
    )

    traces: list[go.Heatmap | go.Scatter] = [heatmap]

    if path:
        path_cols = [c for _r, c in path]
        path_rows = [r for r, _c in path]

        path_line = go.Scatter(
            x=path_cols,
            y=path_rows,
            mode="lines+markers",
            line={"color": "cyan", "width": 2},
            marker={
                "color": "cyan",
                "size": 4,
            },
            name="Path",
            hovertemplate="row=%{y}, col=%{x}<extra>Path</extra>",
        )
        traces.append(path_line)

        # Start marker — green circle
        start_row, start_col = path[0]
        start_marker = go.Scatter(
            x=[start_col],
            y=[start_row],
            mode="markers",
            marker={"color": "green", "size": 12, "symbol": "circle"},
            name="Start",
            hovertemplate=f"Start: row={start_row}, col={start_col}<extra></extra>",
        )
        traces.append(start_marker)

        # Goal marker — red square
        goal_row, goal_col = path[-1]
        goal_marker = go.Scatter(
            x=[goal_col],
            y=[goal_row],
            mode="markers",
            marker={"color": "red", "size": 12, "symbol": "square"},
            name="Goal",
            hovertemplate=f"Goal: row={goal_row}, col={goal_col}<extra></extra>",
        )
        traces.append(goal_marker)

    fig = go.Figure(data=traces)
    fig.update_layout(
        title={"text": title, "x": 0.5, "xanchor": "center"},
        xaxis={"title": "Column", "scaleanchor": "y", "scaleratio": 1},
        yaxis={"title": "Row", "autorange": "reversed"},
        legend={"title": "Legend"},
        margin={"l": 60, "r": 20, "t": 60, "b": 60},
    )

    fig.write_html(str(output_path))
    logger.info("Path visualisation saved to %s", output_path)
    return output_path
