import { useFrame, useThree } from "@react-three/fiber";
import { Vector3 } from "three";
import type { Group } from "three";
import type { RefObject } from "react";
import { useAppStore } from "../store";

// Module-level temporaries — avoid allocating on every frame
const tmpPos = new Vector3();
const tmpDesired = new Vector3();
const tmpLookAt = new Vector3();
const DEFAULT_CAM = new Vector3(40, 40, 40);

export function FollowCamera({ roverRef }: { roverRef: RefObject<Group> }) {
  const cameraMode = useAppStore((s) => s.cameraMode);
  const { camera } = useThree();

  useFrame((_, delta) => {
    if (cameraMode !== "follow") return;

    const rover = roverRef.current;
    if (!rover) {
      // No rover yet — drift back to overview position
      camera.position.lerp(DEFAULT_CAM, Math.min(delta * 2, 1));
      camera.lookAt(0, 2, 0);
      return;
    }

    // Read the rover's actual interpolated world position (not the logical cell)
    rover.getWorldPosition(tmpPos);

    // Camera sits 12 units behind and 6 units above the rover
    const heading = rover.rotation.y;
    tmpDesired.set(
      tmpPos.x - Math.sin(heading) * 12,
      tmpPos.y + 6,
      tmpPos.z - Math.cos(heading) * 12,
    );

    camera.position.lerp(tmpDesired, Math.min(delta * 2.5, 1));

    tmpLookAt.set(tmpPos.x, tmpPos.y + 1, tmpPos.z);
    camera.lookAt(tmpLookAt);
  });

  return null;
}
