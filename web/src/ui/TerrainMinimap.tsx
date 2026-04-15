import { useRef, useEffect, useState } from "react";
import { useAppStore } from "../store";

export function TerrainMinimap() {
  const terrain = useAppStore((s) => s.terrain);
  const mask = useAppStore((s) => s.traversableMask);
  const customStart = useAppStore((s) => s.customStart);
  const setCustomStart = useAppStore((s) => s.setCustomStart);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // "blocked" drives the red-border flash + inline message on a rejected click.
  const [blocked, setBlocked] = useState<string | null>(null);

  function flashBlocked(reason: string) {
    setBlocked(reason);
    setTimeout(() => setBlocked(null), 1400);
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !terrain || !terrain.elevation || terrain.elevation.length === 0) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const elevation = terrain.elevation;
    const rows = elevation.length;
    const cols = elevation[0]?.length ?? 0;
    if (rows === 0 || cols === 0) return;

    const SIZE = 160;
    canvas.width = SIZE;
    canvas.height = SIZE;

    // Clear canvas with a dark background
    ctx.fillStyle = "#0a0504";
    ctx.fillRect(0, 0, SIZE, SIZE);

    // Compute elevation range
    let minE = Infinity;
    let maxE = -Infinity;
    for (let r = 0; r < rows; r++) {
      const row = elevation[r];
      if (!row) continue;
      for (let c = 0; c < cols; c++) {
        const v = row[c];
        if (v < minE) minE = v;
        if (v > maxE) maxE = v;
      }
    }
    const range = maxE - minE || 1;

    const cellW = SIZE / cols;
    const cellH = SIZE / rows;

    for (let r = 0; r < rows; r++) {
      const row = elevation[r];
      if (!row) continue;
      for (let c = 0; c < cols; c++) {
        const v = row[c];
        const t = (v - minE) / range; // 0..1
        // Mars gradient: dark brown -> orange -> tan
        let red = Math.round(74 + t * (216 - 74));
        let green = Math.round(30 + t * (155 - 30));
        let blue = Math.round(14 + t * (106 - 14));
        // Darken cells that are poor mission-start candidates.
        if (mask && mask[r] && !mask[r][c]) {
          red = Math.round(red * 0.2 + 20);
          green = Math.round(green * 0.2 + 20);
          blue = Math.round(blue * 0.2 + 30);
        }
        ctx.fillStyle = `rgb(${red}, ${green}, ${blue})`;
        ctx.fillRect(c * cellW, r * cellH, Math.ceil(cellW), Math.ceil(cellH));
      }
    }

    // Draw selected cell marker (single small green circle)
    if (customStart) {
      const [sr, sc] = customStart;
      const x = (sc + 0.5) * cellW;
      const y = (sr + 0.5) * cellH;
      ctx.fillStyle = "#22c55e";
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#000";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }, [terrain, mask, customStart]);

  if (
    !terrain ||
    !terrain.elevation ||
    terrain.elevation.length === 0 ||
    !terrain.elevation[0]
  ) {
    return (
      <div className="w-[160px] h-[160px] flex items-center justify-center bg-black/40 border border-white/20 rounded text-xs text-gray-500">
        No terrain loaded
      </div>
    );
  }

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || !terrain) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const cols = terrain.elevation[0]?.length ?? 0;
    const rows = terrain.elevation.length;
    if (rows === 0 || cols === 0) return;
    const col = Math.max(0, Math.min(cols - 1, Math.floor((x / rect.width) * cols)));
    const row = Math.max(0, Math.min(rows - 1, Math.floor((y / rect.height) * rows)));

    // Mask not ready yet — traversability analysis is still loading
    if (!mask) {
      flashBlocked("Terrain analysis loading…");
      return;
    }

    // Cell is in the mask but flagged as not a good start (too steep / isolated)
    if (!mask[row]?.[col]) {
      flashBlocked("Too steep — pick a lighter area");
      return;
    }

    setCustomStart([row, col]);
  };

  return (
    <div className="relative">
      <canvas
        ref={canvasRef}
        width={160}
        height={160}
        className={`cursor-crosshair rounded block transition-[border-color,box-shadow] duration-150 ${
          blocked !== null
            ? "border border-red-500 shadow-[0_0_0_2px_rgba(239,68,68,0.35)]"
            : "border border-white/20"
        }`}
        onClick={handleClick}
      />
      {/* Inline rejection message — appears directly below the canvas */}
      {blocked !== null && (
        <div className="absolute left-0 right-0 -bottom-5 text-center text-[9px] text-red-400 font-medium animate-pulse pointer-events-none">
          {blocked}
        </div>
      )}
    </div>
  );
}
