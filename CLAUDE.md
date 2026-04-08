# CLAUDE.md — MarsOps Project Context

## Project Mission

MarsOps is an autonomous Mars rover mission planner. It ingests terrain data
(elevation maps, hazard layers), plans optimal traverse paths under energy and
time constraints, simulates rover physics, streams telemetry, and visualises
results — all orchestrated by Claude Code sub-agents communicating through a
custom MCP server. The goal is aerospace-grade reliability: every module is
strictly typed, thoroughly tested, and reviewed by an automated code-review agent.

## Tech Stack

- **Language:** Python >=3.11 (strict typing, modern syntax)
- **Build / env:** uv (lockfile-based), hatchling (src layout)
- **Core libs:** NumPy, SciPy, NetworkX, Rasterio
- **Viz:** Plotly, Matplotlib
- **API layer:** FastAPI + Uvicorn
- **HTTP client:** httpx
- **Data validation:** Pydantic v2
- **AI integration:** MCP SDK (`mcp` package)
- **Linting:** Ruff (E, F, I, N, UP, B, SIM, RUF rules)
- **Type checking:** mypy (strict mode)
- **Testing:** pytest + pytest-cov + Hypothesis
- **CI:** GitHub Actions

## Repository Layout

```
marsops/
├── src/marsops/          # Installable package (src layout)
│   ├── __init__.py       # Package root, exports __version__
│   ├── terrain/          # Terrain analysis & elevation models
│   ├── planner/          # Path planning & mission scheduling
│   ├── simulator/        # Rover physics simulation
│   ├── telemetry/        # Telemetry ingestion & storage
│   ├── viz/              # Visualisation & dashboards
│   └── mcp_server/       # MCP server for Claude Code integration
├── tests/                # Mirrors src/marsops/ structure
├── data/                 # Local data (raw/ is gitignored)
├── docs/                 # Architecture docs & ADRs
├── .claude/
│   ├── agents/           # Claude Code sub-agent definitions
│   └── hooks/            # Claude Code hook scripts
├── .github/workflows/    # CI pipelines
├── CLAUDE.md             # This file
├── pyproject.toml        # Project metadata, deps, tool config
└── uv.lock               # Locked dependency graph
```

## Coding Conventions

- **Type hints required** on all function signatures and return types.
- **Ruff-clean:** code must pass `uv run ruff check .` with zero warnings.
- **mypy-strict:** code must pass `uv run mypy src` with no errors.
- **No `print()` statements.** Use the `logging` module instead.
- **Docstrings:** Google-style docstrings on every public function and class.
- **Max line length:** 100 characters (enforced by Ruff).
- **Imports:** sorted by Ruff (isort rules via `I` selector).
- **Naming:** PEP 8 — `snake_case` for functions/variables, `PascalCase` for classes.

## Testing Conventions

- Framework: **pytest** with **pytest-cov**.
- Use **Hypothesis** for property-based tests where appropriate (numeric
  algorithms, serialisation round-trips, constraint solvers).
- Every module under `src/marsops/` must have a corresponding
  `tests/test_<module>.py` file.
- Target **>=80 % line coverage** (`--cov-report=term-missing`).
- Tests must be deterministic. Seed RNGs explicitly when randomness is involved.

## Workflow Rules

Before declaring any task done, **always** run:

```bash
uv run ruff check .
uv run mypy src
uv run pytest
```

All three must pass. If pytest reports only "no tests collected" (exit code 5),
that is acceptable during scaffolding but must be resolved before merging.

## Sub-Agent Roster

| Agent | Status | Description |
|-------|--------|-------------|
| `code-reviewer` | Implemented | Reviews code for types, docs, lint, tests, and bugs |
| `terrain-analyst` | Planned | Processes and validates terrain/elevation data |
| `path-planner` | Planned | Generates and optimises rover traverse plans |
| `simulator-runner` | Planned | Executes physics simulations and reports results |
| `telemetry-monitor` | Planned | Watches telemetry streams for anomalies |
| `doc-writer` | Planned | Generates and updates documentation |
| `test-generator` | Planned | Creates test cases from specifications |

## MCP Server Plan

The MCP server (`src/marsops/mcp_server/`) will expose MarsOps capabilities as
tools that Claude Code sub-agents can invoke. Planned tools include terrain
queries, path-planning requests, simulation launches, and telemetry retrieval.
The server runs on FastAPI/Uvicorn and speaks the MCP protocol via the `mcp`
SDK. Each tool will have a Pydantic model for input validation and structured
JSON output.

## Definition of Done

For any feature or change to be considered complete:

- [ ] Code is type-hinted and passes `mypy --strict`
- [ ] Code is formatted and lint-clean (`ruff check` + `ruff format`)
- [ ] All public functions have Google-style docstrings
- [ ] New code has corresponding tests (>=80 % coverage for touched files)
- [ ] All existing tests still pass
- [ ] No `print()` calls — use `logging`
- [ ] No hardcoded secrets or paths
- [ ] The code-reviewer sub-agent returns `VERDICT: APPROVE`
- [ ] CI pipeline passes
