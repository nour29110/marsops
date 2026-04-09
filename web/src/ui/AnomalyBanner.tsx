import { useAppStore } from "../store";

export function AnomalyBanner() {
  const anomaly = useAppStore((s) => s.activeAnomaly);
  if (!anomaly || anomaly === "dust_storm") return null;

  const config: Record<string, { icon: string; text: string; color: string }> = {
    wheel_stuck: { icon: "⚙", text: "WHEEL STUCK", color: "text-orange-400" },
    thermal_alert: { icon: "🔥", text: "THERMAL ALERT", color: "text-red-400" },
  };

  const c = config[anomaly];
  if (!c) return null;

  return (
    <div className="absolute inset-x-0 top-24 flex justify-center pointer-events-none z-20">
      <div
        className={`flex items-center gap-3 px-6 py-3 text-2xl font-bold tracking-widest ${c.color} drop-shadow-[0_2px_8px_rgba(0,0,0,0.9)] animate-pulse`}
      >
        <span>{c.icon}</span>
        <span>{c.text}</span>
      </div>
    </div>
  );
}
