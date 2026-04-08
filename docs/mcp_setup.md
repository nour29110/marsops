# Connecting MarsOps to Claude Desktop via MCP

## What is MCP?

The Model Context Protocol (MCP) is an open standard that lets AI assistants like Claude call
external tools and services at runtime.  An MCP server exposes named tools over a stdio (or HTTP)
transport; Claude Desktop discovers and calls them automatically during a conversation.

## Prerequisites

1. **Claude Desktop** installed on your Mac (download from <https://claude.ai/download>).
2. **marsops** project cloned and dependencies installed:
   ```bash
   cd /Users/mohamadnour/Downloads/marsops
   uv sync
   ```
   The `marsops-mcp` console script is registered automatically by `uv sync`.

## Locating the Claude Desktop Config File

On macOS the config file lives at:

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Open a Finder window, press **Cmd+Shift+G**, and paste the path above.  If the file does not
exist yet, create it (plain JSON, UTF-8).

## Adding the MarsOps Server

Open `claude_desktop_config.json` in any text editor and add (or merge) the `mcpServers` block:

```json
{
  "mcpServers": {
    "marsops": {
      "command": "uv",
      "args": ["--directory", "/Users/mohamadnour/Downloads/marsops", "run", "marsops-mcp"]
    }
  }
}
```

If the file already contains other servers, add `"marsops"` as a sibling key inside the existing
`mcpServers` object.

## Restarting Claude Desktop

You **must fully quit** Claude Desktop — not just close the window.  Press **Cmd+Q** (or choose
*Claude → Quit Claude* from the menu bar), then reopen it.  Claude will start the MarsOps server
automatically in the background the next time a conversation opens.

## Verifying the Connection

After reopening Claude Desktop:

1. Start a new conversation.
2. Look for the **🔌 plug icon** near the text input bar and click it.
3. You should see **marsops** listed with **6 tools**:
   - `load_terrain`
   - `get_terrain_info`
   - `plan_mission`
   - `execute_mission`
   - `inject_anomaly`
   - `get_last_mission_report`

If the server does not appear, check `~/Library/Logs/Claude/mcp-server-marsops.log` for errors.

## Sample Prompts

Once connected, try these prompts in Claude Desktop:

### 1 — Explore the terrain

> "Load the synthetic Jezero terrain and tell me about it."

Claude will call `load_terrain` then `get_terrain_info` and describe the elevation range,
grid size, and resolution.

### 2 — Plan, execute, and read the report

> "Plan a mission starting at row 10 col 10 to survey two waypoints in the northwest quadrant,
> then execute it and show me the report."

Claude will call `plan_mission` (with an ROI covering the NW quadrant), then `execute_mission`,
and finally `get_last_mission_report` to display the sol-style Markdown debrief.

### 3 — Full end-to-end with anomaly injection

> "Load the terrain, plan a mission from (10,10) with 2 waypoints, inject a dust storm at step 3,
> then execute the mission and tell me what happened."

Claude will chain all six tools — loading terrain, planning, injecting the anomaly, executing with
recovery, and retrieving the final report — in a single multi-turn sequence.
