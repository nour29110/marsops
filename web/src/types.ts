export interface TerrainData {
  shape: [number, number];
  elevation: number[][];
  resolution_m: number;
  source: string;
}

export interface TelemetryEvent {
  event_type:
    | "mission_start"
    | "step"
    | "waypoint_reached"
    | "low_battery"
    | "anomaly"
    | "recovery_replan"
    | "mission_complete"
    | "mission_failed"
    | "replay_complete";
  position?: [number, number];
  battery_pct?: number;
  elevation_m?: number;
  heading_deg?: number;
  timestamp_s?: number;
  message?: string;
}

export interface MissionPlanResult {
  status: string;
  feasible: boolean;
  waypoints: [number, number][];
  path_length: number;
  predicted_duration_s: number;
  predicted_final_battery_pct: number;
  reasoning: string;
}
