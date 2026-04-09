import { useRef } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stars } from "@react-three/drei";
import type { Group } from "three";
import { Terrain } from "./Terrain";
import { Rover } from "./Rover";
import { PathLine } from "./PathLine";
import { FollowCamera } from "./FollowCamera";
import { useAppStore } from "../store";

export function MarsScene() {
  const cameraMode = useAppStore((s) => s.cameraMode);

  // Shared ref: Rover writes its real interpolated position here every frame;
  // FollowCamera reads from it so the camera tracks smooth motion, not cell snaps.
  const roverRef = useRef<Group>(null);

  return (
    <Canvas
      className="w-full h-full"
      camera={{ position: [40, 40, 40], fov: 50 }}
      shadows
    >
      {/* Background */}
      <color attach="background" args={["#1a0a05"]} />
      <fog attach="fog" args={["#3a1e0e", 80, 300]} />

      {/* Stars */}
      <Stars radius={300} depth={50} count={2000} factor={4} fade />

      {/* Lighting */}
      <ambientLight intensity={0.3} />
      <directionalLight
        position={[50, 80, 30]}
        intensity={1.2}
        castShadow
        shadow-mapSize={[2048, 2048]}
      />
      <hemisphereLight args={["#ff9966", "#3a1e0e", 0.4]} />

      {/* Camera */}
      <FollowCamera roverRef={roverRef} />
      {cameraMode === "free" && (
        <OrbitControls
          enableDamping
          minDistance={10}
          maxDistance={200}
          maxPolarAngle={Math.PI / 2.2}
        />
      )}

      {/* Scene objects */}
      <Terrain />
      <PathLine />
      <Rover ref={roverRef} />
    </Canvas>
  );
}
