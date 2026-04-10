import { forwardRef, useImperativeHandle, useRef, useMemo, useEffect } from "react";
import { useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import * as THREE from "three";
import { useAppStore } from "../store";

const ROVER_SCALE = 1.0;
const HEIGHT_SCALE = 8;
const Y_OFFSET = 0.35;

export const Rover = forwardRef<THREE.Group>(function Rover(_, fwdRef) {
  const terrain = useAppStore((s) => s.terrain);
  const roverCell = useAppStore((s) => s.roverCell);
  const roverHeading = useAppStore((s) => s.roverHeading);
  const path = useAppStore((s) => s.path);

  const { scene } = useGLTF("/models/curiosity.glb");

  // Internal ref used by useFrame; fwdRef exposes the same element externally
  const groupRef = useRef<THREE.Group>(null);
  useImperativeHandle(fwdRef, () => groupRef.current!);

  // Smooth visual position / heading / tilt — updated every frame, decoupled from store events
  const visualPosRef = useRef(new THREE.Vector3());
  const visualQuatRef = useRef(new THREE.Quaternion());

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

  // Discrete target position + terrain surface normal derived from store state
  const targetData = useMemo(() => {
    if (!terrain || !roverCell || !elevData) return null;
    const [row, col] = roverCell;
    const { elev, cols, rows, minE, range } = elevData;
    const clampedRow = Math.max(0, Math.min(row, rows - 1));
    const clampedCol = Math.max(0, Math.min(col, cols - 1));
    const normalizedH = ((elev[clampedRow][clampedCol] - minE) / range) * HEIGHT_SCALE;
    const pos = new THREE.Vector3(col - cols / 2, normalizedH + Y_OFFSET, row - rows / 2);

    // Compute terrain surface normal from neighbouring cells
    const hAt = (r: number, c: number) => {
      const cr = Math.max(0, Math.min(r, rows - 1));
      const cc = Math.max(0, Math.min(c, cols - 1));
      return ((elev[cr][cc] - minE) / range) * HEIGHT_SCALE;
    };
    const dydx = hAt(clampedRow, clampedCol + 1) - hAt(clampedRow, clampedCol - 1);
    const dydz = hAt(clampedRow + 1, clampedCol) - hAt(clampedRow - 1, clampedCol);
    const normal = new THREE.Vector3(-dydx, 2, -dydz).normalize();

    return { pos, normal };
  }, [terrain, roverCell, elevData]);

  // Snap visual position to start of new mission when path changes
  useEffect(() => {
    if (targetData) {
      visualPosRef.current.copy(targetData.pos);
    }
  }, [path]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reusable scratch objects (avoids allocations per frame)
  const _up = useMemo(() => new THREE.Vector3(0, 1, 0), []);
  const _tiltQuat = useMemo(() => new THREE.Quaternion(), []);
  const _headingQuat = useMemo(() => new THREE.Quaternion(), []);
  const _targetQuat = useMemo(() => new THREE.Quaternion(), []);

  useFrame((_, delta) => {
    if (!groupRef.current || !targetData) return;

    const { pos: target, normal } = targetData;

    // Snap on first placement, otherwise lerp smoothly (frame-rate-independent)
    if (visualPosRef.current.distanceTo(target) > 30) {
      visualPosRef.current.copy(target);
    } else {
      visualPosRef.current.lerp(target, Math.min(delta * 1.5, 1));
    }
    groupRef.current.position.copy(visualPosRef.current);

    // Build target orientation: tilt to terrain normal + heading rotation
    _tiltQuat.setFromUnitVectors(_up, normal);
    const headingAngle = (Math.PI / 180) * roverHeading + Math.PI;
    _headingQuat.setFromAxisAngle(_up, headingAngle);
    _targetQuat.copy(_tiltQuat).multiply(_headingQuat);

    // Smooth slerp towards target orientation
    visualQuatRef.current.slerp(_targetQuat, Math.min(delta * 3.0, 1));
    groupRef.current.quaternion.copy(visualQuatRef.current);
  });

  if (!terrain || !roverCell) return null;

  return (
    <group ref={groupRef} scale={[ROVER_SCALE, ROVER_SCALE, ROVER_SCALE]}>
      {/* Cyan glow light attached to rover */}
      <pointLight color="#00e5ff" intensity={0.6} distance={8} decay={2} />
      <primitive object={scene.clone()} />
    </group>
  );
});
