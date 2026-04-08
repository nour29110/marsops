import { useMemo } from "react";
import * as THREE from "three";
import { useAppStore } from "../store";

const HEIGHT_SCALE = 8;

export function Terrain() {
  const terrain = useAppStore((s) => s.terrain);

  const { geometry, wireGeometry } = useMemo(() => {
    if (!terrain) return { geometry: null, wireGeometry: null };

    const elev = terrain.elevation;
    // Use actual elevation dimensions — backend may downsample so terrain.shape
    // can be larger than elev.length / elev[0].length.
    const rows = elev.length;
    const cols = elev[0]?.length ?? 0;
    if (rows === 0 || cols === 0) return { geometry: null, wireGeometry: null };

    // Flatten elevation and compute min/max for normalization
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
    const indices: number[] = [];

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const idx = r * cols + c;
        const normalizedH = ((elev[r][c] - minE) / range) * HEIGHT_SCALE;
        positions[idx * 3] = c - cols / 2;
        positions[idx * 3 + 1] = normalizedH;
        positions[idx * 3 + 2] = r - rows / 2;
      }
    }

    // Build triangle indices
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
    geo.setIndex(indices);
    geo.computeVertexNormals();

    // Wireframe geometry
    const wireGeo = new THREE.WireframeGeometry(geo);

    return { geometry: geo, wireGeometry: wireGeo };
  }, [terrain]);

  if (!terrain || !geometry || !wireGeometry) return null;

  return (
    <group>
      <mesh geometry={geometry} receiveShadow castShadow>
        <meshStandardMaterial
          color="#b8562f"
          roughness={0.9}
          metalness={0.05}
        />
      </mesh>
      <lineSegments geometry={wireGeometry}>
        <lineBasicMaterial color="#7a3820" transparent opacity={0.3} />
      </lineSegments>
    </group>
  );
}
