import { useEffect } from "react";
import { useAppStore } from "../store";
import type { TelemetryEvent } from "../types";

function defaultWsUrl(): string {
  const apiUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";
  // Convert http(s):// to ws(s)://
  const wsBase = apiUrl.replace(/^http/, "ws");
  return `${wsBase}/ws/telemetry`;
}

export function useTelemetrySocket(wsUrl = defaultWsUrl()) {
  useEffect(() => {
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => console.log("WS connected");
    ws.onmessage = (e) => {
      try {
        const event: TelemetryEvent = JSON.parse(e.data as string);
        useAppStore.getState().applyTelemetry(event);
      } catch {
        /* ignore malformed messages */
      }
    };
    ws.onerror = (e) => console.error("WS error", e);
    ws.onclose = () => console.log("WS closed");
    return () => ws.close();
  }, [wsUrl]);
}
