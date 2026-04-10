import type { TerrainData, MissionPlanResult } from "../types";

const BASE_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchTerrain(): Promise<TerrainData> {
  const res = await fetch(`${BASE_URL}/api/terrain`);
  return handleResponse<TerrainData>(res);
}

export async function fetchTraversableMask(): Promise<{ shape: [number, number]; mask: boolean[][] }> {
  const res = await fetch(`${BASE_URL}/api/terrain/traversable`);
  return handleResponse<{ shape: [number, number]; mask: boolean[][] }>(res);
}

const KEEPALIVE_INTERVAL_MS = 4 * 60 * 1000; // 4 minutes
let keepAliveTimer: ReturnType<typeof setInterval> | null = null;

export function startKeepAlive(): () => void {
  if (keepAliveTimer) return () => {};
  const ping = () => {
    fetch(`${BASE_URL}/healthz`).catch(() => {});
  };
  ping();
  keepAliveTimer = setInterval(ping, KEEPALIVE_INTERVAL_MS);
  return () => {
    if (keepAliveTimer) {
      clearInterval(keepAliveTimer);
      keepAliveTimer = null;
    }
  };
}

export async function sendCommand(
  text: string,
  opts: { replaySpeedMs?: number } = {},
): Promise<{ parsed: unknown; result: MissionPlanResult | unknown }> {
  const body: Record<string, unknown> = { text };
  if (opts.replaySpeedMs !== undefined) {
    body.replay_speed_ms = opts.replaySpeedMs;
  }
  const res = await fetch(`${BASE_URL}/api/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<{ parsed: unknown; result: MissionPlanResult | unknown }>(res);
}
