import { useState, useEffect, useRef } from "react";
import { useAppStore } from "../store";

export function MissionComplete() {
  const missionStatus = useAppStore((s) => s.missionStatus);
  const missionRecovered = useAppStore((s) => s.missionRecovered);
  const prevStatusRef = useRef(missionStatus);
  const [visible, setVisible] = useState(false);
  const [fadeOut, setFadeOut] = useState(false);
  // Capture whether we're showing a complete or failed overlay — once the
  // animation starts we keep the right icon even if missionStatus changes.
  const [overlayType, setOverlayType] = useState<"complete" | "failed" | null>(null);

  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = missionStatus;

    const triggered =
      prev === "running" &&
      (missionStatus === "complete" || missionStatus === "failed");

    if (triggered) {
      setOverlayType(missionStatus);
      setVisible(true);
      setFadeOut(false);
      const fadeTimer = setTimeout(() => setFadeOut(true), 1800);
      const hideTimer = setTimeout(() => setVisible(false), 2600);
      return () => {
        clearTimeout(fadeTimer);
        clearTimeout(hideTimer);
      };
    }

    if (missionStatus === "idle") {
      setVisible(false);
      setFadeOut(false);
      setOverlayType(null);
    }
  }, [missionStatus]);

  if (!visible || !overlayType) return null;

  const wrapCls = `absolute inset-0 z-30 flex items-center justify-center pointer-events-none transition-opacity duration-700 ${
    fadeOut ? "opacity-0" : "opacity-100"
  }`;

  // ── FAILED overlay ──────────────────────────────────────────────────────
  if (overlayType === "failed") {
    return (
      <div className={wrapCls}>
        <div className="flex flex-col items-center gap-3 animate-mission-complete">
          <svg
            className="w-20 h-20 drop-shadow-[0_0_24px_rgba(239,68,68,0.55)]"
            viewBox="0 0 80 80"
            fill="none"
          >
            <circle
              cx="40" cy="40" r="36"
              stroke="rgba(239,68,68,0.25)"
              strokeWidth="3"
            />
            <circle
              cx="40" cy="40" r="36"
              stroke="#ef4444"
              strokeWidth="3"
              strokeLinecap="round"
              strokeDasharray="226"
              strokeDashoffset="226"
              className="animate-check-circle"
            />
            {/* X line 1: top-left → bottom-right */}
            <path
              d="M26 26 L54 54"
              stroke="#ef4444"
              strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray="40"
              strokeDashoffset="40"
              className="animate-check-mark"
            />
            {/* X line 2: top-right → bottom-left, slightly delayed */}
            <path
              d="M54 26 L26 54"
              stroke="#ef4444"
              strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray="40"
              strokeDashoffset="40"
              className="animate-check-mark"
              style={{ animationDelay: "0.85s" }}
            />
          </svg>
          <span className="text-red-400 text-sm font-semibold uppercase tracking-widest drop-shadow-[0_2px_8px_rgba(0,0,0,0.9)]">
            Mission Failed
          </span>
          <span className="text-[11px] font-medium uppercase tracking-[0.35em] text-red-300/80">
            Battery Exhausted
          </span>
        </div>
      </div>
    );
  }

  // ── COMPLETE overlay ─────────────────────────────────────────────────────
  const accent = missionRecovered
    ? {
        glow: "drop-shadow-[0_0_24px_rgba(56,189,248,0.55)]",
        strokeSoft: "rgba(56,189,248,0.28)",
        stroke: "#38bdf8",
        text: "text-sky-300",
        subtitle: "Recovered",
      }
    : {
        glow: "drop-shadow-[0_0_24px_rgba(34,197,94,0.5)]",
        strokeSoft: "rgba(34,197,94,0.3)",
        stroke: "#22c55e",
        text: "text-green-400",
        subtitle: "",
      };

  return (
    <div className={wrapCls}>
      <div className="flex flex-col items-center gap-3 animate-mission-complete">
        <svg
          className={`w-20 h-20 ${accent.glow}`}
          viewBox="0 0 80 80"
          fill="none"
        >
          <circle
            cx="40" cy="40" r="36"
            stroke={accent.strokeSoft}
            strokeWidth="3"
          />
          <circle
            cx="40" cy="40" r="36"
            stroke={accent.stroke}
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray="226"
            strokeDashoffset="226"
            className="animate-check-circle"
          />
          <path
            d="M24 42l10 10 22-24"
            stroke={accent.stroke}
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="60"
            strokeDashoffset="60"
            className="animate-check-mark"
          />
        </svg>
        <span
          className={`${accent.text} text-sm font-semibold uppercase tracking-widest drop-shadow-[0_2px_8px_rgba(0,0,0,0.9)]`}
        >
          Mission Complete
        </span>
        {accent.subtitle && (
          <span className="text-[11px] font-medium uppercase tracking-[0.35em] text-sky-200/90">
            {accent.subtitle}
          </span>
        )}
      </div>
    </div>
  );
}
