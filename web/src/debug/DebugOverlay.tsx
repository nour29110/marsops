import { useEffect, useRef, useState } from "react";
import { useAppStore, type DebugEntry } from "../store";

type FilterCategory = "all" | DebugEntry["category"];

function formatTime(ts: number): string {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  const ms = String(d.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

function entryColor(entry: DebugEntry): string {
  if (entry.level === "error") return "text-red-400";
  if (entry.level === "warn") return "text-yellow-400";
  switch (entry.category) {
    case "network":
      return "text-blue-400";
    case "state":
      return "text-green-400";
    case "user":
      return "text-purple-400";
    default:
      return "text-gray-400";
  }
}

function DebugPanel() {
  const debugLog = useAppStore((s) => s.debugLog);
  const clearDebug = useAppStore((s) => s.clearDebug);
  const toggleDebug = useAppStore((s) => s.toggleDebug);

  const [filter, setFilter] = useState<FilterCategory>("all");
  const [copied, setCopied] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);

  const filtered =
    filter === "all" ? debugLog : debugLog.filter((e) => e.category === filter);

  useEffect(() => {
    if (isAtBottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filtered.length]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 20;
  }

  async function handleCopy() {
    const ts = new Date().toISOString();
    const lines = [
      `=== MarsOps Debug Log (${ts}) ===`,
      `Filter: ${filter}`,
      `Total entries: ${filtered.length}`,
      "",
      ...filtered.map((e) => {
        const line = `[${formatTime(e.timestamp)}] [${e.category.toUpperCase()}] [${e.level}] ${e.message}`;
        return e.details
          ? `${line}\n  ${e.details.split("\n").join("\n  ")}`
          : line;
      }),
    ].join("\n");
    await navigator.clipboard.writeText(lines);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 h-[40vh] flex flex-col bg-black/95 border-t border-white/20 font-mono text-xs">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/10 shrink-0">
        <span className="text-orange-400 font-semibold text-sm">Debug</span>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as FilterCategory)}
          className="bg-black/60 border border-white/10 rounded px-1 py-0.5 text-gray-300 text-xs"
        >
          <option value="all">all</option>
          <option value="error">errors</option>
          <option value="network">network</option>
          <option value="console">console</option>
          <option value="state">state</option>
          <option value="user">user</option>
        </select>
        <div className="flex-1" />
        <button
          onClick={() => void handleCopy()}
          className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 transition-colors"
        >
          {copied ? "Copied!" : "Copy all"}
        </button>
        <button
          onClick={clearDebug}
          className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 transition-colors"
        >
          Clear
        </button>
        <button
          onClick={toggleDebug}
          className="px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 transition-colors"
        >
          ×
        </button>
      </div>

      {/* Log entries */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5"
      >
        {filtered.length === 0 && (
          <div className="text-gray-600 italic">No entries.</div>
        )}
        {filtered.map((entry) => (
          <div key={entry.id} className={`leading-tight ${entryColor(entry)}`}>
            <span className="opacity-60">[{formatTime(entry.timestamp)}]</span>{" "}
            <span className="opacity-80">[{entry.category.toUpperCase()}]</span>{" "}
            <span className="opacity-80">[{entry.level}]</span>{" "}
            <span>{entry.message}</span>
            {entry.details && (
              <div className="pl-4 opacity-60 whitespace-pre-wrap">
                {entry.details}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function DebugOverlay() {
  const debugOpen = useAppStore((s) => s.debugOpen);
  const toggleDebug = useAppStore((s) => s.toggleDebug);
  const errorCount = useAppStore(
    (s) => s.debugLog.filter((e) => e.level === "error").length,
  );

  return (
    <>
      {/* Always-visible toggle button */}
      <button
        onClick={toggleDebug}
        className={`fixed bottom-4 right-4 z-50 px-3 py-1.5 rounded text-sm font-mono shadow-lg transition-colors ${
          errorCount > 0
            ? "bg-red-700 hover:bg-red-600 text-white"
            : "bg-gray-700 hover:bg-gray-600 text-gray-200"
        }`}
      >
        🐞 Debug ({errorCount})
      </button>

      {/* Panel — only mounted when open */}
      {debugOpen && <DebugPanel />}
    </>
  );
}
