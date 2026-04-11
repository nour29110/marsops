import { useEffect, useRef } from "react";
import { useAppStore } from "../store";
import type { LogEntry } from "../store";

const MAX_VISIBLE = 3;

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
  const stackRef = useRef<HTMLDivElement>(null);

  const visible = eventLog.slice(-MAX_VISIBLE);

  useEffect(() => {
    const el = stackRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [visible.length]);

  if (visible.length === 0) return null;

  return (
    <div className="relative w-[240px] pointer-events-none">
      <div
        ref={stackRef}
        className="space-y-1"
      >
      {visible.map((entry, idx) => {
        const colorCls = SEVERITY_COLOR[entry.severity];
        const ageFromNewest = visible.length - 1 - idx;
        const opacity = ageFromNewest === 0 ? 1 : ageFromNewest === 1 ? 0.68 : 0.3;
        const translateY = ageFromNewest === 0 ? 0 : ageFromNewest === 1 ? -4 : -8;
        const scale = ageFromNewest === 0 ? 1 : ageFromNewest === 1 ? 0.98 : 0.95;
        return (
          <div
            key={entry.id}
            className={`flex items-start gap-2 text-[11px] animate-log-enter w-full rounded-lg bg-black/38 backdrop-blur-sm border border-white/8 px-2.5 py-1.5 ${colorCls}`}
            style={{
              filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.8))",
              opacity,
              transform: `translateY(${translateY}px) scale(${scale})`,
              transformOrigin: "top center",
              transition: "opacity 220ms ease, transform 220ms ease",
            }}
          >
            <span className="shrink-0 leading-4">{entry.icon}</span>
            <span className="flex-1 break-words leading-4">
              {entry.text}
            </span>
            {missionStartAt != null && (
              <span className="shrink-0 text-[10px] text-gray-500 leading-4">
                {formatElapsed(missionStartAt, entry.timestamp)}
              </span>
            )}
          </div>
        );
      })}
      </div>
    </div>
  );
}
