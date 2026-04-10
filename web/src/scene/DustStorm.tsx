import { useRef, useState, useEffect, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { RefObject } from "react";
import { useAppStore } from "../store";

const PARTICLE_COUNT = 1500;

function makeDustTexture(): THREE.Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const gradient = ctx.createRadialGradient(
    size / 2, size / 2, 0,
    size / 2, size / 2, size / 2,
  );
  gradient.addColorStop(0, "rgba(200, 120, 70, 1)");
  gradient.addColorStop(0.4, "rgba(160, 90, 50, 0.6)");
  gradient.addColorStop(1, "rgba(100, 50, 20, 0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

export function DustStorm({ roverRef }: { roverRef: RefObject<THREE.Group | null> }) {
  const activeAnomaly = useAppStore((s) => s.activeAnomaly);
  const isDustStorm = activeAnomaly === "dust_storm";

  const [mounted, setMounted] = useState(false);
  const pointsRef = useRef<THREE.Points>(null);
  const elapsedRef = useRef(0);
  const unmountFired = useRef(false);

  const dustTexture = useMemo(() => makeDustTexture(), []);

  const { geometry, basePositions } = useMemo(() => {
    const arr = new Float32Array(PARTICLE_COUNT * 3);
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const angle = Math.random() * Math.PI * 2;
      const radius = Math.random() * 15;
      arr[i * 3] = Math.cos(angle) * radius;
      arr[i * 3 + 1] = Math.pow(Math.random(), 2) * 10;
      arr[i * 3 + 2] = Math.sin(angle) * radius;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(arr.slice(), 3));
    return { geometry: geo, basePositions: arr };
  }, []);

  useEffect(() => {
    return () => {
      geometry.dispose();
      dustTexture.dispose();
    };
  }, [geometry, dustTexture]);

  // Mount and reset state on each dust storm activation
  useEffect(() => {
    if (isDustStorm) {
      const posAttr = geometry.attributes.position as THREE.BufferAttribute;
      (posAttr.array as Float32Array).set(basePositions);
      posAttr.needsUpdate = true;
      elapsedRef.current = 0;
      unmountFired.current = false;
      setMounted(true);
    }
  }, [isDustStorm, geometry, basePositions]);

  useFrame((_, delta) => {
    if (!pointsRef.current) return;

    const mat = pointsRef.current.material as THREE.PointsMaterial;
    elapsedRef.current += delta;
    const t = elapsedRef.current;

    // Fade in at 2/s → 0.45 max; fade out at 0.5/s → ~2s
    if (isDustStorm) {
      mat.opacity = Math.min(mat.opacity + delta * 2.0, 0.45);
    } else {
      const next = Math.max(mat.opacity - delta * 0.5, 0);
      mat.opacity = next;
      if (next < 0.01 && !unmountFired.current) {
        unmountFired.current = true;
        setMounted(false);
      }
    }

    // Slow Y-axis rotation
    pointsRef.current.rotation.y += delta * 0.3;

    // Per-particle sinusoidal drift
    const posAttr = pointsRef.current.geometry.attributes
      .position as THREE.BufferAttribute;
    const buf = posAttr.array as Float32Array;
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      buf[i * 3] += Math.cos(t * 0.7 + i) * 0.005;
      buf[i * 3 + 1] += Math.sin(t + i) * 0.005;
    }
    posAttr.needsUpdate = true;

    // Track rover world position
    if (roverRef.current) {
      pointsRef.current.position.copy(roverRef.current.position);
    }
  });

  if (!mounted) return null;

  return (
    <points ref={pointsRef} geometry={geometry}>
      <pointsMaterial
        map={dustTexture}
        size={0.4}
        transparent
        opacity={0}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        alphaTest={0.01}
        sizeAttenuation
      />
    </points>
  );
}
