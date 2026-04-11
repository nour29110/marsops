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
    let disposed = false;

    ws.onmessage = (e) => {
      try {
        const event: TelemetryEvent = JSON.parse(e.data as string);
        useAppStore.getState().applyTelemetry(event);
      } catch {
        /* ignore malformed messages */
      }
    };
    ws.onerror = () => {
      /* connection failures are transient during local reloads / cold starts */
    };
    ws.onclose = () => {
      /* silent close */
    };

    return () => {
      disposed = true;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;

      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
        return;
      }

      if (ws.readyState === WebSocket.CONNECTING) {
        ws.onopen = () => {
          if (disposed) ws.close();
        };
      }
    };
  }, [wsUrl]);
}
