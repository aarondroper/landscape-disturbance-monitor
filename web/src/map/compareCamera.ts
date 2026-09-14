import type { DisturbanceCollection } from "../data/types";
import { cameraSnapshotOf, fitInitialDisturbanceCamera, type CameraSnapshot, type InitialFitMap } from "./camera";

/** Apply the one authoritative Compare camera after the compare sync controller exists. */
export function applyInitialCompareCamera(
  beforeMap: InitialFitMap,
  afterMap: InitialFitMap,
  disturbances: DisturbanceCollection,
  initialCamera: CameraSnapshot | undefined,
): CameraSnapshot {
  if (!initialCamera) fitInitialDisturbanceCamera(beforeMap, disturbances);
  const authoritativeCamera = initialCamera ?? cameraSnapshotOf(beforeMap);
  beforeMap.jumpTo(authoritativeCamera);
  afterMap.jumpTo(authoritativeCamera);
  return authoritativeCamera;
}
