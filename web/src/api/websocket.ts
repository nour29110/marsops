import { useEffect } from "react";
import { useAppStore } from "../store";
import type { TelemetryEvent } from "../types";

export function useTelemetrySocket(wsUrl = "ws://localhost:8000/ws/telemetry") {
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
