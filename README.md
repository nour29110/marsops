# MarsOps

**Autonomous Mars rover mission planner powered by AI sub-agents.**

> Status: 🚧 In early development

## What is this?

MarsOps is a mission planning system for autonomous Mars rovers. It ingests
terrain data (elevation maps, hazard layers), plans optimal traverse paths under
energy and time constraints, simulates rover physics, streams telemetry, and
visualises results. The system is orchestrated by specialized Claude Code
sub-agents that communicate through a custom MCP (Model Context Protocol) server,
enabling AI-assisted mission planning at aerospace-grade reliability standards.

## Architecture

<!-- TODO: Add architecture diagram -->

See [docs/architecture.md](docs/architecture.md) for details.

## Quick Start

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Lint & type-check
uv run ruff check .
uv run mypy src
```

## Planned Features

- **Terrain Analysis** — ingest and process Mars elevation/hazard data (HiRISE, CTX)
- **Path Planning** — energy- and time-constrained traverse optimization via graph search
- **Physics Simulation** — rover dynamics, wheel–soil interaction, power budgets
- **Telemetry** — real-time ingestion, anomaly detection, and historical analysis
- **Visualization** — interactive 3D terrain views and mission dashboards
- **MCP Server** — expose all capabilities as tools for Claude Code sub-agents
- **AI Code Review** — automated review agent enforcing aerospace-grade standards

## Built With

- [Python 3.11+](https://python.org) with strict typing
- [uv](https://github.com/astral-sh/uv) for dependency management
- [FastAPI](https://fastapi.tiangolo.com) + [Uvicorn](https://uvicorn.org) for the API layer
- [NumPy](https://numpy.org), [SciPy](https://scipy.org), [NetworkX](https://networkx.org) for computation
- [Rasterio](https://rasterio.readthedocs.io) for geospatial raster data
- [Plotly](https://plotly.com/python/) + [Matplotlib](https://matplotlib.org) for visualization
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sub-agents & [MCP](https://modelcontextprotocol.io) for AI orchestration
