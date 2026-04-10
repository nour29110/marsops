import { useAppStore } from "../store";
import type { LogEntry } from "../store";

const MAX_VISIBLE = 12;
/** Oldest N visible entries get a fade-out effect when the log is full. */
const FADE_COUNT = 3;

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

  const applyFade = eventLog.length > MAX_VISIBLE;

  return (
    <div className="w-[320px] flex flex-col gap-0.5 pointer-events-none">
      {visible.map((entry, idx) => {
        const colorCls = SEVERITY_COLOR[entry.severity];
        const opacity =
          applyFade && idx < FADE_COUNT
            ? 0.3 + (idx / FADE_COUNT) * 0.5
            : 1;
        return (
          <div
            key={entry.id}
            className={`flex items-start gap-2 text-sm animate-log-enter w-full ${colorCls}`}
            style={{
              filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.8))",
              opacity,
            }}
          >
            <span className="shrink-0 leading-5">{entry.icon}</span>
            <span className="flex-1 break-words leading-5">
              {entry.text}
            </span>
            {missionStartAt != null && (
              <span className="shrink-0 text-xs text-gray-500 leading-5">
                {formatElapsed(missionStartAt, entry.timestamp)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
