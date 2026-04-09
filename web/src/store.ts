import { create } from "zustand";
import type { TerrainData, TelemetryEvent } from "./types";

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
}

export const useAppStore = create<AppState>((set) => ({
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
  applyTelemetry: (e) =>
    set((state) => {
      const patch: Partial<AppState> = {};
      if (e.event_type === "mission_start") patch.missionStatus = "running";
      if (e.event_type === "mission_complete") patch.missionStatus = "complete";
      if (e.event_type === "mission_failed") patch.missionStatus = "failed";
      if (e.position) patch.roverCell = e.position;
      if (e.heading_deg !== undefined) patch.roverHeading = e.heading_deg;
      if (e.battery_pct !== undefined) patch.batteryPct = e.battery_pct;
      return patch;
    }),
  reset: () =>
    set({
      path: [],
      roverCell: null,
      roverHeading: 0,
      batteryPct: 100,
      missionStatus: "idle",
    }),
}));
