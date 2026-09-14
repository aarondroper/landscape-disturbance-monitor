import type * as maplibregl from "maplibre-gl";
import { calculateBounds } from "../data/loadData";
import type { DisturbanceCollection } from "../data/types";

/** Shared initial framing for Compare, Disturbance, and Recovery. */
export const MAP_FIT_PADDING = {
  top: 88,
  right: 24,
  bottom: 64,
  left: 24,
};

export const INITIAL_FIT_ZOOM_OFFSET = 0.35;
const SMALL_VIEWPORT_MAX_WIDTH = 900;
const SMALL_VIEWPORT_INITIAL_FIT_ZOOM_OFFSET = 0.2;
const INITIAL_FIT_MAX_ZOOM = 11;

export function initialFitZoomOffsetForViewport(viewportWidth: number): number {
  return viewportWidth <= SMALL_VIEWPORT_MAX_WIDTH
    ? SMALL_VIEWPORT_INITIAL_FIT_ZOOM_OFFSET
    : INITIAL_FIT_ZOOM_OFFSET;
}

export interface InitialFitMap {
  resize: () => void;
  fitBounds: (
    bounds: [[number, number], [number, number]],
    options: { padding: typeof MAP_FIT_PADDING; maxZoom: number; duration: 0 },
  ) => void;
  getCenter: () => maplibregl.LngLatLike;
  getZoom: () => number;
  getContainer: () => HTMLElement;
  jumpTo: (options: CameraSnapshot) => void;
  getBearing: () => number;
  getPitch: () => number;
}

/** Fit the shared initial view to disturbance geography, then tighten it modestly. */
export function fitInitialDisturbanceCamera(map: InitialFitMap, disturbances: DisturbanceCollection | undefined): boolean {
  const bounds = calculateBounds(disturbances);
  if (!bounds) return false;
  const [west, south, east, north] = bounds;
  map.resize();
  map.fitBounds([[west, south], [east, north]], {
    padding: MAP_FIT_PADDING,
    maxZoom: INITIAL_FIT_MAX_ZOOM,
    duration: 0,
  });

  const zoom = map.getZoom() + initialFitZoomOffsetForViewport(map.getContainer().clientWidth);
  map.jumpTo({
    center: [(west + east) / 2, (south + north) / 2],
    zoom,
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  });
  return true;
}

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
