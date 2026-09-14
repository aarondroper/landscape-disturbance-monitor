import type { DisturbanceCollection } from "../data/types";
import { calculateBounds } from "../data/loadData";
import { cameraSnapshotOf, fitInitialDisturbanceCamera, type CameraSnapshot, type InitialFitMap } from "./camera";

export interface CompareCameraReadiness {
  mapsReady: boolean;
  compareReady: boolean;
  dimensionsReady: boolean;
  disturbances?: DisturbanceCollection;
  initialCamera?: CameraSnapshot;
}

export function hasValidMapDimensions(...containers: HTMLElement[]): boolean {
  return containers.every((container) => container.clientWidth > 0 && container.clientHeight > 0);
}

export function hasValidDisturbanceBounds(disturbances: DisturbanceCollection | undefined): boolean {
  return calculateBounds(disturbances) !== undefined;
}

export function createCompareCameraInitializer(beforeMap: InitialFitMap, afterMap: InitialFitMap) {
  let initialized = false;

  return {
    isInitialized: () => initialized,
    tryInitialize: (readiness: CompareCameraReadiness): CameraSnapshot | undefined => {
      if (
        initialized ||
        !readiness.mapsReady ||
        !readiness.compareReady ||
        !readiness.dimensionsReady
      ) {
        return undefined;
      }

      if (!readiness.initialCamera && !hasValidDisturbanceBounds(readiness.disturbances)) return undefined;
      const camera = applyInitialCompareCamera(beforeMap, afterMap, readiness.disturbances, readiness.initialCamera);
      if (!camera) return undefined;
      initialized = true;
      return camera;
    },
  };
}

/** Apply the one authoritative Compare camera after the compare sync controller exists. */
export function applyInitialCompareCamera(
  beforeMap: InitialFitMap,
  afterMap: InitialFitMap,
  disturbances: DisturbanceCollection | undefined,
  initialCamera: CameraSnapshot | undefined,
): CameraSnapshot | undefined {
  if (!initialCamera && !fitInitialDisturbanceCamera(beforeMap, disturbances)) return undefined;
  const authoritativeCamera = initialCamera ?? cameraSnapshotOf(beforeMap);
  beforeMap.jumpTo(authoritativeCamera);
  afterMap.jumpTo(authoritativeCamera);
  return authoritativeCamera;
}
