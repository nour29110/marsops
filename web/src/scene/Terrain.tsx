import { useMemo } from "react";
import * as THREE from "three";
import { useAppStore } from "../store";

const HEIGHT_SCALE = 8;

// Elevation colour stops (normalized 0-1)
const COLOR_LOW = new THREE.Color("#4a1e0e");
const COLOR_MID = new THREE.Color("#b8562f");
const COLOR_HIGH = new THREE.Color("#d89b6a");

function elevColor(t: number): THREE.Color {
  if (t < 0.3) {
    return COLOR_LOW.clone().lerp(COLOR_MID, t / 0.3);
  } else if (t < 0.7) {
    return COLOR_MID.clone().lerp(COLOR_HIGH, (t - 0.3) / 0.4);
  }
  return COLOR_MID.clone().lerp(COLOR_HIGH, (t - 0.3) / 0.4);
}

export function Terrain() {
  const terrain = useAppStore((s) => s.terrain);

  const geometry = useMemo(() => {
    if (!terrain) return null;

    const elev = terrain.elevation;
    // Use actual elevation dimensions — backend may downsample so terrain.shape
    // can be larger than elev.length / elev[0].length.
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

    const positions = new Float32Array(rows * cols * 3);
    const colors = new Float32Array(rows * cols * 3);
    const indices: number[] = [];

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const idx = r * cols + c;
        const raw = elev[r][c];
        const t = (raw - minE) / range;
        const normalizedH = t * HEIGHT_SCALE;

        positions[idx * 3] = c - cols / 2;
        positions[idx * 3 + 1] = normalizedH;
        positions[idx * 3 + 2] = r - rows / 2;

        const col = elevColor(t);
        colors[idx * 3] = col.r;
        colors[idx * 3 + 1] = col.g;
        colors[idx * 3 + 2] = col.b;
      }
    }

    for (let r = 0; r < rows - 1; r++) {
      for (let c = 0; c < cols - 1; c++) {
        const a = r * cols + c;
        const b = a + 1;
        const d = a + cols;
        const e = d + 1;
        indices.push(a, d, b);
        indices.push(b, d, e);
      }
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();
    return geo;
  }, [terrain]);

  if (!terrain || !geometry) return null;

  return (
    <group>
      {/* Ground disc so the terrain doesn't float */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.1, 0]}>
        <circleGeometry args={[200, 64]} />
        <meshStandardMaterial color="#2a0e04" roughness={1} metalness={0} />
      </mesh>

      <mesh geometry={geometry}>
        <meshStandardMaterial
          vertexColors
          roughness={0.95}
          metalness={0}
        />
      </mesh>
    </group>
  );
}
