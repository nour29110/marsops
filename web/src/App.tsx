import { useEffect } from "react";
import { MarsScene } from "./scene/MarsScene";
import { MissionControls } from "./ui/MissionControls";
import { EventLog } from "./ui/EventLog";
import { AnomalyBanner } from "./ui/AnomalyBanner";
import { TerrainMinimap } from "./ui/TerrainMinimap";
import { CameraToggle } from "./ui/CameraToggle";
import { MissionComplete } from "./ui/MissionComplete";
import { ReportModal } from "./ui/ReportModal";
import { sendCommand, fetchTerrain, fetchTraversableMask } from "./api/client";
import { useTelemetrySocket } from "./api/websocket";
import { useAppStore } from "./store";
import { ErrorBoundary } from "./debug/ErrorBoundary";

const STATUS_COLORS: Record<string, string> = {
  idle: "text-gray-400",
  running: "text-yellow-400",
  complete: "text-green-400",
  failed: "text-red-400",
};

function ReportBanner({
  status,
  onView,
}: {
  status: "complete" | "failed";
  onView: () => void;
}) {
  const isComplete = status === "complete";
  return (
    <div
      className={`flex items-center gap-2 px-3 py-2 rounded border text-xs font-medium ${
        isComplete
          ? "border-green-500/40 bg-green-900/30 text-green-300"
          : "border-red-500/40 bg-red-900/30 text-red-300"
      }`}
    >
      <span>{isComplete ? "✓ Report ready" : "✕ Mission failed — report available"}</span>
      <button
        onClick={onView}
        className={`ml-auto px-2 py-0.5 rounded border text-[11px] transition-colors ${
          isComplete
            ? "border-green-500/50 hover:bg-green-800/50 text-green-200"
            : "border-red-500/50 hover:bg-red-800/50 text-red-200"
        }`}
      >
        View
      </button>
    </div>
  );
}

export default function App() {
  const terrain = useAppStore((s) => s.terrain);
  const customStart = useAppStore((s) => s.customStart);
  const setCustomStart = useAppStore((s) => s.setCustomStart);
  const roverCell = useAppStore((s) => s.roverCell);
  const batteryPct = useAppStore((s) => s.batteryPct);
  const roverHeading = useAppStore((s) => s.roverHeading);
  const missionStatus = useAppStore((s) => s.missionStatus);

  useTelemetrySocket();

  function handleViewReport() {
    const store = useAppStore.getState();
    store.setReportLoading(true);
    store.setReportOpen(true);
    sendCommand("report")
      .then((resp) => {
        const r = (
          resp as {
            parsed: unknown;
            result: { status: string; markdown?: string; message?: string };
          }
        ).result;
        store.setReportContent(r.markdown ?? r.message ?? "No report content.");
      })
      .catch(() => {
        store.setReportContent("Failed to load report from the server.");
      })
      .finally(() => {
        store.setReportLoading(false);
      });
  }

  // Proactively initialize terrain on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await sendCommand("load synthetic terrain");
        if (cancelled) return;
        const terrain = await fetchTerrain();
        if (cancelled) return;
        useAppStore.getState().setTerrain(terrain);
        try {
          const m = await fetchTraversableMask();
          if (!cancelled) {
            useAppStore.getState().setTraversableMask(m.mask);
          }
        } catch {
          /* mask is optional */
        }
      } catch (err) {
        console.error("Initial terrain load failed:", err);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="relative w-screen h-screen overflow-hidden">
      {/* 3D Canvas — full screen */}
      <div className="absolute inset-0">
        <ErrorBoundary>
          <MarsScene />
        </ErrorBoundary>
      </div>

      {/* Top-left: Telemetry HUD */}
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

      {/* Top-right: Mission Control */}
      <div className="absolute top-4 right-4 z-10 flex flex-col gap-3 items-end">
        <ErrorBoundary>
          <MissionControls />
        </ErrorBoundary>
      </div>

      {/* Left-side: event log + report banner */}
      <div className="absolute left-4 top-[11rem] bottom-[14.5rem] z-10 flex flex-col justify-center gap-3 items-start">
        <EventLog />
        {(missionStatus === "complete" || missionStatus === "failed") && (
          <ReportBanner status={missionStatus} onView={handleViewReport} />
        )}
      </div>

      {/* Bottom-left: Terrain minimap for picking a custom start cell */}
      {terrain && (
        <div className="absolute bottom-4 left-4 z-10 bg-black/40 backdrop-blur-sm border border-white/10 rounded-lg p-2">
          <div className="text-[10px] text-orange-400 uppercase tracking-wider mb-1 px-1">
            Click to set start
          </div>
          <TerrainMinimap />
          {customStart && (
            <button
              onClick={() => setCustomStart(null)}
              className="text-[10px] text-gray-400 hover:text-white mt-1 px-1"
            >
              Reset to preset start
            </button>
          )}
        </div>
      )}

      {/* Bottom-right: Camera mode toggle */}
      <div className="absolute bottom-4 right-4 z-10">
        <CameraToggle />
      </div>

      {/* Centered: Anomaly banner (wheel/thermal only) */}
      <AnomalyBanner />

      {/* Centered: Mission complete checkmark */}
      <MissionComplete />

      {/* Report viewer modal — sits above everything else */}
      <ReportModal />
    </div>
  );
}
