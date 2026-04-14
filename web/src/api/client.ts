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
  const res = await fetchWithRetry(`${BASE_URL}/api/terrain`);
  return handleResponse<TerrainData>(res);
}

export async function fetchTraversableMask(): Promise<{ shape: [number, number]; mask: boolean[][] }> {
  const res = await fetchWithRetry(`${BASE_URL}/api/terrain/traversable`);
  return handleResponse<{ shape: [number, number]; mask: boolean[][] }>(res);
}

async function fetchWithRetry(
  input: RequestInfo,
  init?: RequestInit,
): Promise<Response> {
  const res = await fetch(input, init);
  if (!res.ok && res.status >= 500) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res;
}

export async function sendCommand(
  text: string,
  opts: { replaySpeedMs?: number } = {},
): Promise<{ parsed: unknown; result: MissionPlanResult | unknown }> {
  const body: Record<string, unknown> = { text };
  if (opts.replaySpeedMs !== undefined) {
    body.replay_speed_ms = opts.replaySpeedMs;
  }
  const res = await fetchWithRetry(`${BASE_URL}/api/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse<{ parsed: unknown; result: MissionPlanResult | unknown }>(res);
}
