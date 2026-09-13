import type * as maplibregl from "maplibre-gl";

/** Shared initial framing for Compare, Disturbance, and Recovery. */
export const MAP_FIT_PADDING = {
  top: 88,
  right: 348,
  bottom: 64,
  left: 24,
};

export interface CameraSnapshot {
  center: maplibregl.LngLatLike;
  zoom: number;
  bearing: number;
  pitch: number;
}

interface CameraSnapshotSource {
  getCenter: () => maplibregl.LngLatLike;
  getZoom: () => number;
  getBearing: () => number;
  getPitch: () => number;
}

export function cameraSnapshotOf(map: CameraSnapshotSource): CameraSnapshot {
  return {
    center: map.getCenter(),
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  };
}

export function sameCameraSnapshot(left: CameraSnapshot | undefined, right: CameraSnapshot | undefined): boolean {
  if (!left || !right) return left === right;
  const centerPair = (center: maplibregl.LngLatLike): [number, number] => {
    if (Array.isArray(center)) return [center[0], center[1]];
    if ("lng" in center) return [center.lng, center.lat];
    return [center.lon, center.lat];
  };
  const leftCenter = centerPair(left.center);
  const rightCenter = centerPair(right.center);
  return leftCenter[0] === rightCenter[0]
    && leftCenter[1] === rightCenter[1]
    && left.zoom === right.zoom
    && left.bearing === right.bearing
    && left.pitch === right.pitch;
}
