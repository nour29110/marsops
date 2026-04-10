import { useState, useEffect } from "react";
import { useAppStore } from "../store";

export function MissionComplete() {
  const missionStatus = useAppStore((s) => s.missionStatus);
  const [visible, setVisible] = useState(false);
  const [fadeOut, setFadeOut] = useState(false);

  useEffect(() => {
    if (missionStatus === "complete") {
      setVisible(true);
      setFadeOut(false);
      const fadeTimer = setTimeout(() => setFadeOut(true), 1800);
      const hideTimer = setTimeout(() => setVisible(false), 2600);
      return () => {
        clearTimeout(fadeTimer);
        clearTimeout(hideTimer);
      };
    }
    setVisible(false);
    setFadeOut(false);
  }, [missionStatus]);

  if (!visible) return null;

  return (
    <div
      className={`absolute inset-0 z-30 flex items-center justify-center pointer-events-none transition-opacity duration-700 ${
        fadeOut ? "opacity-0" : "opacity-100"
      }`}
    >
      <div className="flex flex-col items-center gap-3 animate-mission-complete">
        {/* Animated checkmark circle */}
        <svg
          className="w-20 h-20 drop-shadow-[0_0_24px_rgba(34,197,94,0.5)]"
          viewBox="0 0 80 80"
          fill="none"
        >
          <circle
            cx="40"
            cy="40"
            r="36"
            stroke="rgba(34,197,94,0.3)"
            strokeWidth="3"
          />
          <circle
            cx="40"
            cy="40"
            r="36"
            stroke="#22c55e"
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray="226"
            strokeDashoffset="226"
            className="animate-check-circle"
          />
          <path
            d="M24 42l10 10 22-24"
            stroke="#22c55e"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="60"
            strokeDashoffset="60"
            className="animate-check-mark"
          />
        </svg>
        <span className="text-green-400 text-sm font-semibold uppercase tracking-widest drop-shadow-[0_2px_8px_rgba(0,0,0,0.9)]">
          Mission Complete
        </span>
      </div>
    </div>
  );
}
