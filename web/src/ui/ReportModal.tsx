import { useAppStore } from "../store";

// ---------------------------------------------------------------------------
// Minimal markdown renderer — no external deps.
// Handles the predictable structure of the MarsOps sol-report:
//   # / ## headers, | table | rows, - list items, **bold**, emoji lines.
// ---------------------------------------------------------------------------

function renderLine(line: string, idx: number): React.ReactNode {
  // H1
  if (line.startsWith("# ")) {
    return (
      <div key={idx} className="text-orange-400 font-bold text-base mt-4 mb-1">
        {line.slice(2)}
      </div>
    );
  }
  // H2
  if (line.startsWith("## ")) {
    return (
      <div key={idx} className="text-white font-semibold text-sm mt-4 mb-1 border-b border-white/10 pb-1">
        {line.slice(3)}
      </div>
    );
  }
  // Table separator row (|---|---|)
  if (/^\|[-| ]+\|$/.test(line.trim())) return null;
  // Table row
  if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
    const cells = line.trim().slice(1, -1).split("|").map((c) => c.trim());
    const isHeader = cells.some((c) => /^[A-Z]/.test(c));
    return (
      <div key={idx} className={`flex gap-0 text-[11px] font-mono ${isHeader ? "text-gray-400" : "text-gray-200"}`}>
        {cells.map((cell, ci) => (
          <span key={ci} className="flex-1 px-2 py-0.5 border-b border-white/5">
            {cell}
          </span>
        ))}
      </div>
    );
  }
  // List item
  if (line.startsWith("- ")) {
    const content = line.slice(2);
    return (
      <div key={idx} className="flex gap-2 text-[11px] text-gray-300 ml-2 my-0.5">
        <span className="text-orange-500 shrink-0">·</span>
        <span>{renderInline(content)}</span>
      </div>
    );
  }
  // Recommendation line (🔴 / 🟡 / 🟢)
  if (line.includes("🔴") || line.includes("🟡") || line.includes("🟢")) {
    const color = line.includes("🔴")
      ? "text-red-400"
      : line.includes("🟡")
        ? "text-yellow-400"
        : "text-green-400";
    return (
      <div key={idx} className={`text-[12px] font-semibold mt-1 ${color}`}>
        {renderInline(line)}
      </div>
    );
  }
  // Empty line → spacer
  if (line.trim() === "") return <div key={idx} className="h-1" />;
  // Default paragraph text
  return (
    <div key={idx} className="text-[11px] text-gray-300 leading-relaxed">
      {renderInline(line)}
    </div>
  );
}

// Converts **bold** spans inside a string into styled elements.
function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="text-white font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return part;
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ReportModal() {
  const reportOpen = useAppStore((s) => s.reportOpen);
  const reportContent = useAppStore((s) => s.reportContent);
  const reportLoading = useAppStore((s) => s.reportLoading);
  const setReportOpen = useAppStore((s) => s.setReportOpen);

  if (!reportOpen) return null;

  function handleDownload() {
    if (!reportContent) return;
    const blob = new Blob([reportContent], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `marsops_report_${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const lines = reportContent ? reportContent.split("\n") : [];

  return (
    // Full-screen overlay
    <div className="absolute inset-0 z-40 flex items-center justify-center">
      {/* Semi-transparent backdrop — click to close */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-[2px]"
        onClick={() => setReportOpen(false)}
      />

      {/* Panel */}
      <div className="relative z-50 w-[660px] max-w-[92vw] max-h-[80vh] bg-black/70 backdrop-blur-md border border-white/10 rounded-xl flex flex-col shadow-[0_8px_40px_rgba(0,0,0,0.7)]">
        {/* Header bar */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/10 shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-orange-400 font-semibold text-xs uppercase tracking-wider">
              Mission Report
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleDownload}
              disabled={!reportContent || reportLoading}
              className="text-[11px] text-gray-400 hover:text-white border border-white/10 hover:border-white/30 rounded px-3 py-1 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              ↓ Download .md
            </button>
            <button
              onClick={() => setReportOpen(false)}
              className="text-gray-400 hover:text-white text-lg leading-none w-7 h-7 flex items-center justify-center rounded hover:bg-white/5 transition-colors"
              aria-label="Close report"
            >
              ×
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 min-h-0 space-y-0.5">
          {reportLoading && (
            <div className="text-gray-500 text-xs text-center py-12 animate-pulse">
              Loading report…
            </div>
          )}
          {!reportLoading && !reportContent && (
            <div className="text-gray-500 text-xs text-center py-12">
              No report available. Run a mission first.
            </div>
          )}
          {!reportLoading && reportContent && lines.map((line, i) => renderLine(line, i))}
        </div>

        {/* Footer hint */}
        {!reportLoading && reportContent && (
          <div className="px-5 py-2 border-t border-white/10 shrink-0">
            <span className="text-[10px] text-gray-600">
              All figures derived from live telemetry — no values are fabricated.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
