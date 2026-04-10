import { useAppStore } from "../store";

const modes = ["follow", "free"] as const;

export function CameraToggle() {
  const cameraMode = useAppStore((s) => s.cameraMode);
  const setCameraMode = useAppStore((s) => s.setCameraMode);

  return (
    <div className="bg-black/60 backdrop-blur-sm border border-white/10 rounded-lg p-2.5 flex items-center gap-2">
      <svg
        className="w-4 h-4 text-orange-400 shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
        <circle cx="12" cy="13" r="4" />
      </svg>
      <div className="flex rounded overflow-hidden border border-white/10">
        {modes.map((mode) => (
          <button
            key={mode}
            onClick={() => setCameraMode(mode)}
            className={`px-3 py-1 text-xs font-medium transition-colors capitalize ${
              cameraMode === mode
                ? "bg-orange-600 text-white"
                : "bg-black/40 text-gray-400 hover:text-white hover:bg-white/5"
            }`}
          >
            {mode}
          </button>
        ))}
      </div>
    </div>
  );
}
