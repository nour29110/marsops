import { useAppStore } from "../store";
import type { LogEntry } from "../store";

const MAX_VISIBLE = 12;

const SEVERITY_COLOR: Record<LogEntry["severity"], string> = {
  info: "text-cyan-300",
  warn: "text-yellow-300",
  error: "text-red-400",
  success: "text-green-400",
};

function formatElapsed(startAt: number, entryAt: number): string {
  const s = Math.max(0, Math.round((entryAt - startAt) / 1000));
  return `+${s}s`;
}

export function EventLog() {
  const eventLog = useAppStore((s) => s.eventLog);
  const missionStartAt = useAppStore((s) => s.missionStartAt);

  const visible = eventLog.slice(-MAX_VISIBLE);
  if (visible.length === 0) return null;

  return (
    <div className="w-[320px] flex flex-col gap-0.5 pointer-events-none">
      {visible.map((entry) => {
        const colorCls = SEVERITY_COLOR[entry.severity];
        return (
          <div
            key={entry.id}
            className={`flex items-center gap-2 text-sm animate-log-enter w-full ${colorCls}`}
            style={{ filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.8))" }}
          >
            <span className="shrink-0">{entry.icon}</span>
            <span className="flex-1 truncate" title={entry.text}>
              {entry.text}
            </span>
            {missionStartAt != null && (
              <span className="shrink-0 text-xs text-gray-500">
                {formatElapsed(missionStartAt, entry.timestamp)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
