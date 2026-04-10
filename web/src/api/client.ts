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

async function fetchWithRetry(
  input: RequestInfo,
  init?: RequestInit,
  retries = 3,
  delayMs = 2000,
): Promise<Response> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(input, init);
      // Render returns 502 while the container is booting — retry
      if (res.status === 502 && attempt < retries) {
        await new Promise((r) => setTimeout(r, delayMs));
        continue;
      }
      return res;
    } catch (err) {
      // Network error (CORS block on a 502, or container unreachable)
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, delayMs));
        continue;
      }
      throw err;
    }
  }
  // Unreachable, but satisfies TS
  throw new Error("fetchWithRetry: exhausted retries");
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
