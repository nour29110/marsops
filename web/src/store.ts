import { create } from "zustand";
import type { TerrainData, TelemetryEvent } from "./types";

export type ActiveAnomaly = "dust_storm" | "wheel_stuck" | "thermal_alert" | "repositioning";

export type MissionPhase =
  | "resetting"
  | "loading_terrain"
  | "analyzing"
  | "planning"
  | "injecting_anomaly"
  | "executing"
  | null;

export interface LogEntry {
  id: string;
  icon: string;
  text: string;
  severity: "info" | "warn" | "error" | "success";
  timestamp: number;
}

export interface DebugEntry {
  id: string;
  timestamp: number;
  category: "console" | "error" | "network" | "state" | "user";
  level: "log" | "info" | "warn" | "error";
  message: string;
  details?: string;
}

interface AppState {
  terrain: TerrainData | null;
  setTerrain: (t: TerrainData) => void;
  path: [number, number][];
  setPath: (p: [number, number][]) => void;
  roverCell: [number, number] | null;
  roverHeading: number;
  batteryPct: number;
  missionStatus: "idle" | "running" | "complete" | "failed";
  setRoverCell: (cell: [number, number]) => void;
  cameraMode: "follow" | "free";
  setCameraMode: (m: "follow" | "free") => void;
  applyTelemetry: (e: TelemetryEvent) => void;
  reset: () => void;
  eventLog: LogEntry[];
  pushLogEntry: (entry: Omit<LogEntry, "id" | "timestamp">) => void;
  clearLog: () => void;
  missionStartAt: number | null;
  activeAnomaly: ActiveAnomaly | null;
  setActiveAnomaly: (a: ActiveAnomaly | null) => void;
  loading: boolean;
  setLoading: (loading: boolean) => void;
  missionPhase: MissionPhase;
  setMissionPhase: (phase: MissionPhase) => void;
  customStart: [number, number] | null;
  setCustomStart: (s: [number, number] | null) => void;
  traversableMask: boolean[][] | null;
  setTraversableMask: (m: boolean[][] | null) => void;
  debugLog: DebugEntry[];
  debugOpen: boolean;
  pushDebug: (entry: Omit<DebugEntry, "id" | "timestamp">) => void;
  clearDebug: () => void;
  toggleDebug: () => void;
}

function makeEntry(
  icon: string,
  text: string,
  severity: LogEntry["severity"],
): LogEntry {
  return {
    id: crypto.randomUUID(),
    icon,
    text: text.slice(0, 60),
    severity,
    timestamp: Date.now(),
  };
}

export const useAppStore = create<AppState>((set, get) => ({
  terrain: null,
  setTerrain: (t) => set({ terrain: t }),
  path: [],
  setPath: (p) => set({ path: p }),
  roverCell: null,
  roverHeading: 0,
  batteryPct: 100,
  missionStatus: "idle",
  setRoverCell: (cell) => set({ roverCell: cell }),
  cameraMode: "follow",
  setCameraMode: (m) => set({ cameraMode: m }),
  eventLog: [],
  pushLogEntry: (entry) =>
    set((state) => {
      const truncated = { ...entry, text: entry.text.slice(0, 60) };
      const next = [
        ...state.eventLog,
        { ...truncated, id: crypto.randomUUID(), timestamp: Date.now() },
      ];
      return { eventLog: next.slice(-20) };
    }),
  clearLog: () => set({ eventLog: [] }),
  missionStartAt: null,
  activeAnomaly: null,
  setActiveAnomaly: (a) => set({ activeAnomaly: a }),
  loading: false,
  setLoading: (loading) => set({ loading }),
  missionPhase: null,
  setMissionPhase: (phase) => set({ missionPhase: phase }),
  customStart: null,
  setCustomStart: (s) => set({ customStart: s }),
  traversableMask: null,
  setTraversableMask: (m) => set({ traversableMask: m }),
  debugLog: [],
  debugOpen: false,
  pushDebug: (entry) =>
    set((state) => {
      const next = [
        ...state.debugLog,
        { ...entry, id: crypto.randomUUID(), timestamp: Date.now() },
      ];
      return { debugLog: next.length > 500 ? next.slice(-500) : next };
    }),
  clearDebug: () => set({ debugLog: [] }),
  toggleDebug: () => set((state) => ({ debugOpen: !state.debugOpen })),
  applyTelemetry: (e) => {
    set((state) => {
      const patch: Partial<AppState> = {};

      // Status transitions
      if (e.event_type === "mission_start") patch.missionStatus = "running";
      if (e.event_type === "mission_complete") patch.missionStatus = "complete";
      if (e.event_type === "mission_failed") patch.missionStatus = "failed";

      // Position / heading / battery
      if (e.position) patch.roverCell = e.position;
      if (e.heading_deg !== undefined) patch.roverHeading = e.heading_deg;
      if (e.battery_pct !== undefined) patch.batteryPct = e.battery_pct;

      // Skip noisy step events
      if (e.event_type === "step") return patch;

      const pos = e.position;
      const posStr = pos ? `(${pos[0]}, ${pos[1]})` : "";

      let newEntry: LogEntry | null = null;

      if (e.event_type === "mission_start") {
        patch.missionStartAt = Date.now();
        newEntry = makeEntry("▶", `Mission started at ${posStr}`, "info");
      } else if (e.event_type === "waypoint_reached") {
        newEntry = makeEntry("📍", `Reached waypoint ${posStr}`, "success");
      } else if (e.event_type === "low_battery") {
        newEntry = makeEntry(
          "⚠",
          `Low battery: ${e.battery_pct?.toFixed(1) ?? "?"}%`,
          "warn",
        );
      } else if (e.event_type === "anomaly") {
        const msg = (e.message ?? "").toLowerCase();
        let type: ActiveAnomaly = "dust_storm";
        if (msg.includes("wheel")) type = "wheel_stuck";
        else if (msg.includes("thermal")) type = "thermal_alert";

        newEntry = makeEntry("⚡", e.message ?? "Anomaly", "warn");
        patch.activeAnomaly = type;
        setTimeout(() => set({ activeAnomaly: null }), 4000);
      } else if (e.event_type === "recovery_replan") {
        newEntry = makeEntry("🔁", `Recovery replan: ${e.message ?? ""}`, "warn");
      } else if (e.event_type === "mission_complete") {
        newEntry = makeEntry("✅", `Mission complete at ${posStr}`, "success");
      } else if (e.event_type === "mission_failed") {
        newEntry = makeEntry("❌", `Mission failed at ${posStr}`, "error");
      }

      if (newEntry) {
        const next = [...state.eventLog, newEntry];
        patch.eventLog = next.slice(-20);
      }

      return patch;
    });
    get().pushDebug({
      category: "state",
      level: "log",
      message: `telemetry: ${e.event_type}${e.position ? ` @ (${e.position[0]},${e.position[1]})` : ""}`,
    });
  },
  reset: () =>
    set({
      path: [],
      roverCell: null,
      roverHeading: 0,
      batteryPct: 100,
      missionStatus: "idle",
      activeAnomaly: null,
      eventLog: [],
      missionStartAt: null,
      missionPhase: null,
    }),
}));
