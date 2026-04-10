import { useMemo } from "react";
import { Line } from "@react-three/drei";
import * as THREE from "three";
import { useAppStore } from "../store";

const HEIGHT_SCALE = 8;
const PATH_Y_OFFSET = 0.7;

export function PathLine() {
  const path = useAppStore((s) => s.path);
  const terrain = useAppStore((s) => s.terrain);

  const points = useMemo(() => {
    if (!path.length || !terrain) return null;

    const elev = terrain.elevation;
    const rows = elev.length;
    const cols = elev[0]?.length ?? 0;
    if (rows === 0 || cols === 0) return null;

    let minE = Infinity;
    let maxE = -Infinity;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const v = elev[r][c];
        if (v < minE) minE = v;
        if (v > maxE) maxE = v;
      }
    }
    const range = maxE - minE || 1;

    return path.map(([row, col]) => {
      const clampedRow = Math.max(0, Math.min(row, rows - 1));
      const clampedCol = Math.max(0, Math.min(col, cols - 1));
      const normalizedH =
        ((elev[clampedRow][clampedCol] - minE) / range) * HEIGHT_SCALE;
      return new THREE.Vector3(
        col - cols / 2,
        normalizedH + PATH_Y_OFFSET,
        row - rows / 2
      );
    });
  }, [path, terrain]);

  if (!points || points.length < 2) return null;

  return (
    <group>
      {/* Outer glow line */}
      <Line
        points={points}
        color="#00e5ff"
        lineWidth={5}
        transparent
        opacity={0.15}
      />
      {/* Core dashed line */}
      <Line
        points={points}
        color="#00e5ff"
        lineWidth={2}
        dashed
        dashSize={0.8}
        gapSize={0.4}
      />
    </group>
  );
}
