import { useRef, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { useAppStore } from "../store";

const ROVER_SCALE = 0.5;
const HEIGHT_SCALE = 8;
const Y_OFFSET = 0.3;

export function Rover() {
  const terrain = useAppStore((s) => s.terrain);
  const roverCell = useAppStore((s) => s.roverCell);
  const roverHeading = useAppStore((s) => s.roverHeading);

  const { scene } = useGLTF("/models/curiosity.glb");
  const groupRef = useRef<THREE.Group>(null);

  // Precompute terrain height lookup
  const elevData = useMemo(() => {
    if (!terrain) return null;
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
    return { elev, rows, cols, minE, range };
  }, [terrain]);

  const target = useMemo(() => {
    if (!terrain || !roverCell || !elevData) return null;
    const [row, col] = roverCell;
    const { elev, cols, rows, minE, range } = elevData;
    const clampedRow = Math.max(0, Math.min(row, rows - 1));
    const clampedCol = Math.max(0, Math.min(col, cols - 1));
    const normalizedH = ((elev[clampedRow][clampedCol] - minE) / range) * HEIGHT_SCALE;
    return new THREE.Vector3(
      col - cols / 2,
      normalizedH + Y_OFFSET,
      row - rows / 2
    );
  }, [terrain, roverCell, elevData]);

  useFrame(() => {
    if (!groupRef.current || !target) return;
    groupRef.current.position.lerp(target, 0.1);
    const targetY = (Math.PI / 180) * roverHeading + Math.PI;
    groupRef.current.rotation.y +=
      (targetY - groupRef.current.rotation.y) * 0.1;
  });

  if (!terrain || !roverCell) return null;

  const initialPos = target ?? new THREE.Vector3(0, 0, 0);

  return (
    <group
      ref={groupRef}
      position={[initialPos.x, initialPos.y, initialPos.z]}
      scale={[ROVER_SCALE, ROVER_SCALE, ROVER_SCALE]}
    >
      <primitive object={scene.clone()} />
    </group>
  );
}
