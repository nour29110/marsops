import { useEffect, useState } from "react";
import { MarsScene } from "./scene/MarsScene";
import { fetchTerrain, sendCommand } from "./api/client";
import { useTelemetrySocket } from "./api/websocket";
import { useAppStore } from "./store";
import type { MissionPlanResult } from "./types";

// Access store outside React to avoid stale closure captures in async handlers
const { getState } = useAppStore;

const STATUS_COLORS: Record<string, string> = {
  idle: "text-gray-400",
  running: "text-yellow-400",
  complete: "text-green-400",
  failed: "text-red-400",
};

export default function App() {
  const terrain = useAppStore((s) => s.terrain);
  const setTerrain = useAppStore((s) => s.setTerrain);
  const roverCell = useAppStore((s) => s.roverCell);
  const batteryPct = useAppStore((s) => s.batteryPct);
  const roverHeading = useAppStore((s) => s.roverHeading);
  const missionStatus = useAppStore((s) => s.missionStatus);
  const cameraMode = useAppStore((s) => s.cameraMode);
  const setCameraMode = useAppStore((s) => s.setCameraMode);

  const [loading, setLoading] = useState(false);

  useTelemetrySocket();

  // Attempt to fetch terrain on mount — silently ignore 404/network errors
  useEffect(() => {
    fetchTerrain()
      .then(setTerrain)
      .catch(() => { /* no terrain loaded yet, ignore */ });
  }, []);

  async function handleLoadTerrain() {
    setLoading(true);
    try {
      await sendCommand("load synthetic terrain");
      const data = await fetchTerrain();
      getState().setTerrain(data);
    } catch (err) {
      console.error("Load terrain error:", err);
    } finally {
      setLoading(false);
    }
  }

  async function handleRunDemo() {
    setLoading(true);
    getState().reset();
    try {
      await sendCommand("reset session");
      await sendCommand("load synthetic terrain");
      const terrainData = await fetchTerrain();
      getState().setTerrain(terrainData);

      const planResponse = await sendCommand(
        "plan a mission from (10,10) with 2 waypoints in the NW quadrant",
      );
      const result = (
        planResponse as { parsed: unknown; result: MissionPlanResult }
      ).result as MissionPlanResult;
      const start: [number, number] = [10, 10];
      const wps: [number, number][] = result?.waypoints ?? [];
      const path: [number, number][] = [start, ...wps];
      getState().setPath(path);
      getState().setRoverCell(path[0]); // pre-position rover at path start

      await sendCommand("inject a dust storm at step 3");
      await sendCommand("execute mission", { replaySpeedMs: 800 });
    } catch (err) {
      console.error("Demo error:", err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative w-screen h-screen overflow-hidden">
      {/* 3D Canvas */}
      <div className="absolute inset-0">
        <MarsScene />
      </div>

      {/* Top-left overlay: telemetry HUD */}
      <div className="absolute top-4 left-4 z-10 bg-black/60 backdrop-blur-sm border border-white/10 rounded-lg p-3 text-sm space-y-1 min-w-[200px]">
        <div className="text-orange-400 font-semibold text-xs uppercase tracking-wider mb-2">
          MarsOps Telemetry
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">Status</span>
          <span className={STATUS_COLORS[missionStatus] ?? "text-white"}>
            {missionStatus.toUpperCase()}
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">Cell</span>
          <span className="text-white">
            {roverCell ? `(${roverCell[0]}, ${roverCell[1]})` : "—"}
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">Battery</span>
          <span
            className={
              batteryPct > 50
                ? "text-green-400"
                : batteryPct > 20
                  ? "text-yellow-400"
                  : "text-red-400"
            }
          >
            {batteryPct.toFixed(1)}%
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-gray-400">Heading</span>
          <span className="text-white">{roverHeading.toFixed(0)}°</span>
        </div>
        {terrain && (
          <div className="flex justify-between gap-4 pt-1 border-t border-white/10">
            <span className="text-gray-400">Terrain</span>
            <span className="text-blue-300 text-xs">
              {terrain.shape[0]}×{terrain.shape[1]}
            </span>
          </div>
        )}
      </div>

      {/* Top-right: 3 buttons */}
      <div className="absolute top-4 right-4 z-10 flex flex-col gap-2">
        <button
          onClick={() => setCameraMode(cameraMode === "follow" ? "free" : "follow")}
          className="px-4 py-2 text-sm rounded bg-zinc-700 hover:bg-zinc-600 text-white font-medium transition-colors"
        >
          {cameraMode === "follow" ? "📷 Free Cam" : "🎯 Follow Cam"}
        </button>

        <div className="border-t border-white/10 my-0.5" />

        <button
          onClick={handleLoadTerrain}
          disabled={loading}
          className="px-4 py-2 text-sm rounded bg-orange-700 hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors"
        >
          {loading ? "Loading…" : "Load Terrain"}
        </button>

        <button
          onClick={handleRunDemo}
          disabled={loading}
          className="px-4 py-2 text-sm rounded bg-blue-700 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium transition-colors"
        >
          {loading ? "Running…" : "🪐 Run Demo Mission"}
        </button>
      </div>
    </div>
  );
}
