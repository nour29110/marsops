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
