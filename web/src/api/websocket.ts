import { useEffect } from "react";
import { useAppStore } from "../store";
import type { TelemetryEvent } from "../types";

export function useTelemetrySocket(wsUrl = "ws://localhost:8000/ws/telemetry") {
  const applyTelemetry = useAppStore((s) => s.applyTelemetry);
  useEffect(() => {
    const ws = new WebSocket(wsUrl);
    ws.onmessage = (e) => {
      try {
        const event: TelemetryEvent = JSON.parse(e.data as string);
        applyTelemetry(event);
      } catch {
        /* ignore malformed messages */
      }
    };
    ws.onerror = (e) => console.error("WS error", e);
    return () => ws.close();
  }, [wsUrl, applyTelemetry]);
}
