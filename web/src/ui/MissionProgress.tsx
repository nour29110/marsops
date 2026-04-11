import { useAppStore, type MissionPhase } from "../store";

const PHASES: { key: MissionPhase; label: string; icon: string }[] = [
  { key: "loading_terrain", label: "Loading terrain data", icon: "1" },
  { key: "analyzing", label: "Analyzing traversability", icon: "2" },
  { key: "planning", label: "Computing optimal route", icon: "3" },
  { key: "injecting_anomaly", label: "Injecting anomaly", icon: "4" },
  { key: "executing", label: "Executing mission", icon: "5" },
];

function phaseIndex(phase: MissionPhase): number {
  return PHASES.findIndex((p) => p.key === phase);
}

export function MissionProgress() {
  const phase = useAppStore((s) => s.missionPhase);

  if (!phase || phase === "resetting") return null;

  const currentIdx = phaseIndex(phase);

  return (
    <div className="mt-3 rounded-lg border border-white/10 bg-black/50 p-3 overflow-hidden">
      <div className="flex items-center gap-2 mb-3">
        <div className="h-2 w-2 rounded-full bg-orange-500 animate-pulse" />
        <span className="text-xs font-semibold text-orange-400 uppercase tracking-wider">
          Preparing Mission
        </span>
      </div>

      <div className="flex flex-col gap-1">
        {PHASES.map((p, i) => {
          const isDone = i < currentIdx;
          const isActive = i === currentIdx;
          const isPending = i > currentIdx;

          return (
            <div
              key={p.key}
              className={`flex items-center gap-2.5 px-2 py-1.5 rounded transition-all duration-300 ${
                isActive
                  ? "bg-orange-500/10 border border-orange-500/30"
                  : isDone
                    ? "opacity-60"
                    : "opacity-30"
              }`}
            >
              {/* Step indicator */}
              <div
                className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
                  isDone
                    ? "bg-green-500/80 text-white"
                    : isActive
                      ? "bg-orange-500 text-white"
                      : "bg-white/10 text-gray-500"
                }`}
              >
                {isDone ? "\u2713" : p.icon}
              </div>

              {/* Label */}
              <span
                className={`text-xs ${
                  isActive
                    ? "text-orange-300 font-medium"
                    : isDone
                      ? "text-gray-400"
                      : "text-gray-600"
                }`}
              >
                {p.label}
              </span>

              {/* Spinner for active step */}
              {isActive && (
                <svg
                  className="ml-auto w-3.5 h-3.5 text-orange-400 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="3"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
              )}

              {/* Checkmark for done */}
              {isDone && isPending === false && (
                <span className="ml-auto text-green-400 text-[10px]" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
