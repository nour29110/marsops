import { useState } from "react";
import { useAppStore } from "../store";
import { sendCommand, fetchTerrain, fetchTraversableMask } from "../api/client";
import { NumberField } from "./NumberField";
import type { MissionPlanResult } from "../types";
import { logUserAction } from "../debug/useLogAction";
import { MissionProgress } from "./MissionProgress";

type AnomalyType = "none" | "dust storm" | "wheel stuck" | "thermal alert";

function findNearestUsableCell(
  start: [number, number],
  mask: boolean[][],
  tried: Set<string>,
): [number, number] | null {
  const [sr, sc] = start;
  const rows = mask.length;
  const cols = mask[0]?.length ?? 0;
  const queue: [number, number][] = [[sr, sc]];
  const visited = new Set<string>([`${sr},${sc}`]);
  while (queue.length) {
    const [r, c] = queue.shift()!;
    const key = `${r},${c}`;
    if (
      !tried.has(key) &&
      r >= 0 &&
      r < rows &&
      c >= 0 &&
      c < cols &&
      mask[r] &&
      mask[r][c]
    ) {
      return [r, c];
    }
    for (const [dr, dc] of [
      [-1, 0],
      [1, 0],
      [0, -1],
      [0, 1],
      [-1, -1],
      [-1, 1],
      [1, -1],
      [1, 1],
    ]) {
      const nr = r + dr;
      const nc = c + dc;
      const nkey = `${nr},${nc}`;
      if (!visited.has(nkey) && nr >= 0 && nr < rows && nc >= 0 && nc < cols) {
        visited.add(nkey);
        queue.push([nr, nc]);
      }
    }
  }
  return null;
}

type MissionPreset = {
  id: string;
  label: string;
  description: string;
  start: [number, number];
  waypoints: number;
  /** Terrain keywords passed to the planner (flat/high/low/delta). */
  keywords: string;
  /** Default anomaly for this preset. */
  defaultAnomaly: AnomalyType;
  defaultAnomalyStep: number;
};

const PRESETS: MissionPreset[] = [
  {
    id: "delta_survey",
    label: "Delta Survey",
    description: "Short traverse across flat, low-elevation delta terrain",
    start: [10, 10],
    waypoints: 2,
    keywords: "delta flat",
    defaultAnomaly: "none",
    defaultAnomalyStep: 3,
  },
  {
    id: "crater_dip",
    label: "Crater Dip",
    description: "Descent into low crater terrain with four science stops",
    start: [15, 15],
    waypoints: 4,
    keywords: "low",
    defaultAnomaly: "dust storm",
    defaultAnomalyStep: 4,
  },
  {
    id: "rim_patrol",
    label: "Rim Patrol",
    description: "Traverse along the high-elevation crater rim",
    start: [12, 8],
    waypoints: 3,
    keywords: "high",
    defaultAnomaly: "wheel stuck",
    defaultAnomalyStep: 3,
  },
];

const INPUT_CLS =
  "bg-black/40 border border-white/10 rounded px-2 py-1 text-sm text-white w-full focus:outline-none focus:border-orange-500/50 disabled:opacity-40 disabled:cursor-not-allowed";
const LABEL_CLS = "text-xs text-gray-400 uppercase tracking-wider mb-0.5 block";

export function MissionControls() {
  const loading = useAppStore((s) => s.loading);
  const missionStatus = useAppStore((s) => s.missionStatus);
  const cameraMode = useAppStore((s) => s.cameraMode);
  const setCameraMode = useAppStore((s) => s.setCameraMode);
  const [selectedPresetId, setSelectedPresetId] = useState(PRESETS[0].id);
  const [anomaly, setAnomaly] = useState<AnomalyType>("dust storm");
  const [anomalyStep, setAnomalyStep] = useState(3);

  const disabled = loading || missionStatus === "running";
  const preset = PRESETS.find((p) => p.id === selectedPresetId)!;

  function selectPreset(id: string) {
    setSelectedPresetId(id);
    const p = PRESETS.find((pr) => pr.id === id)!;
    setAnomaly(p.defaultAnomaly);
    setAnomalyStep(p.defaultAnomalyStep);
    logUserAction(`Selected preset: ${id}`);
  }

  async function handleRun() {
    logUserAction(
      "Run mission",
      JSON.stringify({ preset: selectedPresetId, anomaly, anomalyStep }),
    );
    const store = useAppStore.getState();
    store.setLoading(true);
    store.reset();
    try {
      store.setMissionPhase("resetting");
      await sendCommand("reset session");

      store.setMissionPhase("loading_terrain");
      await sendCommand("load synthetic terrain");
      const t = await fetchTerrain();
      store.setTerrain(t);

      store.setMissionPhase("analyzing");
      try {
        const m = await fetchTraversableMask();
        useAppStore.getState().setTraversableMask(m.mask);
      } catch {
        /* mask is optional, ignore */
      }

      const customStart = useAppStore.getState().customStart;
      const [startRow, startCol] = customStart ?? preset.start;

      // Auto-relocate loop: retry up to 5 times if the planner returns no
      // real waypoints (isolated pocket / edge cell the mask didn't catch).
      const tried = new Set<string>();
      let attempt = 0;
      let planResult: MissionPlanResult | null = null;
      let currentStart: [number, number] = [startRow, startCol];

      store.setMissionPhase("planning");
      while (attempt < 5) {
        tried.add(`${currentStart[0]},${currentStart[1]}`);
        const planText = `plan a mission from (${currentStart[0]},${currentStart[1]}) with ${preset.waypoints} waypoints ${preset.keywords}`;
        const resp = await sendCommand(planText);
        const r = (resp as { parsed: unknown; result: MissionPlanResult })
          .result as MissionPlanResult;

        const realWps = (r?.waypoints ?? []).filter(
          ([wr, wc]) => wr !== currentStart[0] || wc !== currentStart[1],
        );
        if (r?.feasible && realWps.length > 0) {
          planResult = r;
          break;
        }

        // Soft reject — try to relocate via BFS
        const mask = useAppStore.getState().traversableMask;
        if (!mask) break;
        const next = findNearestUsableCell(currentStart, mask, tried);
        if (!next) break;

        store.pushLogEntry({
          icon: "🛠",
          text: `Repositioning rover from (${currentStart[0]},${currentStart[1]}) to (${next[0]},${next[1]})`,
          severity: "warn",
        });
        useAppStore.getState().setCustomStart(next);
        currentStart = next;

        // Show REPOSITIONING banner briefly
        useAppStore.getState().setActiveAnomaly("repositioning");
        setTimeout(() => useAppStore.getState().setActiveAnomaly(null), 1500);
        attempt++;
      }

      if (!planResult) {
        store.pushLogEntry({
          icon: "❌",
          text: `Could not find a usable start near (${startRow},${startCol}). Try a different region.`,
          severity: "error",
        });
        return;
      }

      const path: [number, number][] = [
        [currentStart[0], currentStart[1]],
        ...(planResult.waypoints ?? []),
      ];
      store.setPath(path);
      store.setRoverCell(path[0]);

      if (anomaly !== "none") {
        store.setMissionPhase("injecting_anomaly");
        await sendCommand(`inject a ${anomaly} at step ${anomalyStep}`);
      }
      store.setMissionPhase("executing");
      await sendCommand("execute mission", { replaySpeedMs: 800 });
    } catch (err) {
      console.error("Mission error:", err);
      const msg =
        err instanceof Error ? err.message : "Unknown error";
      useAppStore.getState().pushLogEntry({
        icon: "❌",
        text: `Mission failed: ${msg}. The backend may be waking up — try again in a few seconds.`,
        severity: "error",
      });
    } finally {
      useAppStore.getState().setMissionPhase(null);
      useAppStore.getState().setLoading(false);
    }
  }

  function handleReset() {
    logUserAction("Reset");
    const s = useAppStore.getState();
    s.reset();
    s.setCustomStart(null);
    s.clearLog();
  }

  return (
    <div className="w-[320px] bg-black/40 backdrop-blur-sm border border-white/10 rounded-lg p-4">
      {/* Header */}
      <div className="text-orange-400 font-semibold text-xs uppercase tracking-wider mb-3">
        Mission Control
      </div>

      {/* Preset cards */}
      <div className="flex flex-col gap-1.5 mb-3">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            onClick={() => selectPreset(p.id)}
            disabled={disabled}
            className={`w-full text-left px-3 py-2 rounded border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
              selectedPresetId === p.id
                ? "border-orange-500 bg-orange-950/40"
                : "border-white/10 bg-black/20 hover:border-white/20 hover:bg-black/30"
            }`}
          >
            <div className="text-sm font-medium text-white leading-tight">{p.label}</div>
            <div className="text-xs text-gray-400 mt-0.5 leading-tight">{p.description}</div>
          </button>
        ))}
      </div>

      {/* Anomaly row */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-2 mb-3">
        <div>
          <label className={LABEL_CLS}>Anomaly</label>
          <select
            value={anomaly}
            onChange={(e) => setAnomaly(e.target.value as AnomalyType)}
            disabled={disabled}
            className={INPUT_CLS}
          >
            <option value="none">none</option>
            <option value="dust storm">dust storm</option>
            <option value="wheel stuck">wheel stuck</option>
            <option value="thermal alert">thermal alert</option>
          </select>
        </div>
        {anomaly !== "none" && (
          <div>
            <label className={LABEL_CLS}>At Step</label>
            <NumberField
              value={anomalyStep}
              onChange={setAnomalyStep}
              min={0}
              max={20}
              disabled={disabled}
              className={INPUT_CLS}
            />
            <div className="text-[10px] text-gray-500 mt-1">
              Step where the anomaly fires (0–20). Most missions are 5–15 steps.
            </div>
          </div>
        )}
      </div>

      {/* Scenario reality-check hints */}
      {anomaly !== "none" && anomalyStep <= 1 && (
        <div className="text-[11px] text-yellow-400/80 mt-2 px-2 py-1 border-l-2 border-yellow-400/60 bg-yellow-400/5 rounded-r">
          ⚠ Anomaly at step ≤1 may cut the mission short.
        </div>
      )}
      {anomaly !== "none" && anomalyStep > 12 && (
        <div className="text-[11px] text-yellow-400/80 mt-2 px-2 py-1 border-l-2 border-yellow-400/60 bg-yellow-400/5 rounded-r">
          ⚠ Anomaly at step {anomalyStep} may fire after the mission ends.
        </div>
      )}

      <div className="border-t border-white/10 my-3" />

      {/* Run button */}
      <button
        onClick={() => void handleRun()}
        disabled={disabled}
        className="w-full py-2 text-sm font-semibold rounded bg-orange-600 hover:bg-orange-500 disabled:opacity-40 disabled:cursor-not-allowed text-white transition-colors mb-2"
      >
        {loading ? "Running…" : "▶ Run Mission"}
      </button>

      {/* Live progress steps */}
      <MissionProgress />

      {/* Reset button */}
      <button
        onClick={handleReset}
        disabled={loading}
        className="w-full py-2 text-sm font-medium rounded border border-white/20 bg-transparent hover:bg-white/5 disabled:opacity-40 disabled:cursor-not-allowed text-gray-300 transition-colors mb-3"
      >
        ⟲ Reset
      </button>

      {/* Camera toggle */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400">Camera:</span>
        <button
          onClick={() => setCameraMode("follow")}
          className={`flex-1 py-1 text-xs rounded transition-colors ${
            cameraMode === "follow"
              ? "bg-orange-700 text-white"
              : "bg-black/30 border border-white/10 text-gray-400 hover:text-white"
          }`}
        >
          Follow
        </button>
        <button
          onClick={() => setCameraMode("free")}
          className={`flex-1 py-1 text-xs rounded transition-colors ${
            cameraMode === "free"
              ? "bg-orange-700 text-white"
              : "bg-black/30 border border-white/10 text-gray-400 hover:text-white"
          }`}
        >
          Free
        </button>
      </div>
    </div>
  );
}
