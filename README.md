When an anomaly fires mid-mission, the same loop runs in reverse via `anomaly-handler`, producing a new plan from the rover's current state that is itself validated before the engine resumes. This is the same ground-in-the-loop pattern JPL uses for Perseverance operations, scaled down to a laptop.

## Terrain data

MarsOps supports two terrain sources through the same `Terrain` API:

- **Synthetic**, a deterministic seeded Jezero-like DEM generated from layered sinusoids plus a shallow Gaussian crater and a northwest delta ramp. Fast, reproducible, used by default.
- **Real**, a 9 MB USGS CTX Digital Terrain Model of Jezero Crater pulled from the NASA PDS mirror on first run and cached. This is the same data product Mars 2020 mission planners reference.

Switch at the CLI with `--source real`, or from Claude Desktop by asking for it.

## Quickstart (local)

**Backend:**

```bash
git clone https://github.com/nour29110/marsops.git
cd marsops
uv sync
uv run pytest          # 620 passing, 93% coverage
uv run marsops-web     # FastAPI on http://localhost:8000
```

**Frontend (separate terminal):**

```bash
cd web
npm install
npm run dev            # Vite on http://localhost:5173
```

Open `http://localhost:5173` and click Run Mission.

**Standalone demos (no web UI needed):**

```bash
uv run python scripts/demo_path.py       # A* path on Jezero
uv run python scripts/demo_mission.py    # Full rover sim + telemetry
uv run python scripts/demo_anomaly.py    # Mid-mission anomaly + recovery
```

Each demo writes an interactive HTML file to `output/` that you can open in a browser.

## Driving the rover from Claude Desktop

See [`docs/mcp_setup.md`](docs/mcp_setup.md) for the full setup. In short, start the MCP server, add one snippet to `claude_desktop_config.json`, quit and reopen Claude Desktop, and the six MarsOps tools appear in the tool drawer. Then chat with the rover in plain English.

## Deployment

The live demo is deployed in two pieces:

- **Backend on [Render](https://render.com)**, free tier, as a Docker container built from the `Dockerfile` at the repo root. Configured in [`render.yaml`](render.yaml). Sleeps after 15 minutes of inactivity, which is why the first request after a cold period takes ~30 seconds.
- **Frontend on [Vercel](https://vercel.com)**, free tier, built from the `web/` folder with Vite. Points at the Render backend via `VITE_API_URL`.

Both platforms auto-redeploy on every push to `main` via GitHub integration.

## Built with

- **Language**, Python 3.11 (backend), TypeScript 5 (frontend)
- **Packaging**, [uv](https://github.com/astral-sh/uv) for Python, npm for Node
- **Linting and formatting**, [ruff](https://github.com/astral-sh/ruff)
- **Type checking**, [mypy](http://mypy-lang.org/) in strict mode
- **Testing**, [pytest](https://docs.pytest.org/) with [hypothesis](https://hypothesis.readthedocs.io/) property-based tests
- **Pre-commit**, [pre-commit](https://pre-commit.com/) running ruff and mypy
- **CI**, GitHub Actions
- **Agentic tooling**, [Claude Code](https://github.com/anthropics/claude-code) with seven custom sub-agents, hooks, and a project-level `CLAUDE.md`
- **Natural language interface**, a custom [MCP](https://modelcontextprotocol.io/) server built with the official Python SDK
- **Web API**, [FastAPI](https://fastapi.tiangolo.com/) with a WebSocket telemetry stream
- **Web frontend**, [React](https://react.dev/) 18, [Vite](https://vitejs.dev/), [React Three Fiber](https://r3f.docs.pmnd.rs/), [drei](https://github.com/pmndrs/drei), [zustand](https://github.com/pmndrs/zustand), [Tailwind](https://tailwindcss.com/) v3
- **Geospatial**, numpy, scipy, rasterio, networkx
- **Visualization**, plotly for interactive HTML, matplotlib for static plots
- **Deployment**, Docker, Render (backend), Vercel (frontend)

## Project status

Version 0.2.0. Feature-complete through closed-loop recovery, the Claude Desktop MCP integration, and a deployed 3D web UI with live telemetry streaming. See [`docs/anomaly_recovery_trace.txt`](docs/anomaly_recovery_trace.txt) for a real captured run.

## License

MIT, see [`LICENSE`](LICENSE).