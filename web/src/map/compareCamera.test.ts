import { describe, expect, it } from "vitest";
import type { DisturbanceCollection } from "../data/types";
import type { CameraSnapshot } from "./camera";
import { applyInitialCompareCamera, createCompareCameraInitializer } from "./compareCamera";

const disturbances: DisturbanceCollection = {
  type: "FeatureCollection",
  features: [{
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[14, 60], [18, 60], [18, 64], [14, 64], [14, 60]]] },
    properties: {
      disturbance_id: "disturbance-001",
      area_ha: 1,
      touches_aoi_boundary: false,
      nbr_2017_median: 0.5,
      nbr_2018_median: 0.2,
      dnbr_median: 0.3,
      recovery_2026_median: 0.4,
      recovery_2026_valid_fraction: 1,
      recovery_2026_coverage_status: "GOOD",
      recovery_2026_reporting_recommended: true,
    },
  }],
};

function fakeMap(events: string[], zoom = 9) {
  let camera: CameraSnapshot = { center: [15.5, 61.9], zoom, bearing: 0, pitch: 0 };
  return {
    resize: () => events.push("resize"),
    fitBounds: () => events.push("fitBounds"),
    getZoom: () => camera.zoom,
    getContainer: () => ({ clientWidth: 1680, clientHeight: 900 } as HTMLElement),
    jumpTo: (next: CameraSnapshot) => {
      events.push("jumpTo");
      camera = next;
    },
    getCenter: () => camera.center,
    getBearing: () => camera.bearing,
    getPitch: () => camera.pitch,
    snapshot: () => camera,
  };
}

function applyCompareInitialCamera(
  events: string[],
  beforeMap: ReturnType<typeof fakeMap>,
  afterMap: ReturnType<typeof fakeMap>,
  snapshot: CameraSnapshot | undefined,
): void {
  events.push("compare-sync-ready");
  applyInitialCompareCamera(beforeMap, afterMap, disturbances, snapshot);
}

describe("Compare initial camera lifecycle", () => {
  const ready = {
    mapsReady: true,
    compareReady: true,
    dimensionsReady: true,
  };

  it("does not finalize a cold-start camera while disturbance data is unavailable", () => {
    const events: string[] = [];
    const beforeMap = fakeMap(events);
    const afterMap = fakeMap(events);
    const initializer = createCompareCameraInitializer(beforeMap, afterMap);

    expect(initializer.tryInitialize(ready)).toBeUndefined();
    expect(initializer.isInitialized()).toBe(false);
    expect(events).not.toContain("fitBounds");
  });

  it("waits for valid disturbance bounds and fits exactly once when data arrives later", () => {
    const events: string[] = [];
    const beforeMap = fakeMap(events);
    const afterMap = fakeMap(events);
    const initializer = createCompareCameraInitializer(beforeMap, afterMap);

    expect(initializer.tryInitialize({ ...ready, disturbances: { type: "FeatureCollection", features: [] } })).toBeUndefined();
    expect(initializer.isInitialized()).toBe(false);

    const camera = initializer.tryInitialize({ ...ready, disturbances });
    expect(camera).toEqual({ center: [16, 62], zoom: 9.35, bearing: 0, pitch: 0 });
    expect(initializer.isInitialized()).toBe(true);
    expect(events.filter((event) => event === "fitBounds")).toHaveLength(1);
    expect(events.filter((event) => event === "jumpTo")).toHaveLength(3);
    expect(initializer.tryInitialize({ ...ready, disturbances })).toBeUndefined();
    expect(events.filter((event) => event === "fitBounds")).toHaveLength(1);
    expect(beforeMap.snapshot()).toEqual(afterMap.snapshot());
  });

  it("keeps initialization pending until maps, Compare, and dimensions are ready", () => {
    const events: string[] = [];
    const beforeMap = fakeMap(events);
    const afterMap = fakeMap(events);
    const initializer = createCompareCameraInitializer(beforeMap, afterMap);

    for (const readiness of [
      { ...ready, mapsReady: false, disturbances },
      { ...ready, compareReady: false, disturbances },
      { ...ready, dimensionsReady: false, disturbances },
    ]) {
      expect(initializer.tryInitialize(readiness)).toBeUndefined();
      expect(initializer.isInitialized()).toBe(false);
    }
    expect(events).not.toContain("fitBounds");
  });

  it("waits when data is ready before map and Compare synchronization", () => {
    const events: string[] = [];
    const beforeMap = fakeMap(events);
    const afterMap = fakeMap(events);
    const initializer = createCompareCameraInitializer(beforeMap, afterMap);

    expect(initializer.tryInitialize({ ...ready, mapsReady: false, compareReady: false, disturbances })).toBeUndefined();
    expect(initializer.isInitialized()).toBe(false);
    expect(initializer.tryInitialize({ ...ready, disturbances })).toEqual({
      center: [16, 62],
      zoom: 9.35,
      bearing: 0,
      pitch: 0,
    });
    expect(initializer.isInitialized()).toBe(true);
  });

  it("applies one shared fitted camera after synchronization is ready", () => {
    const events: string[] = [];
    const beforeMap = fakeMap(events);
    const afterMap = fakeMap(events);

    applyCompareInitialCamera(events, beforeMap, afterMap, undefined);

    expect(events.indexOf("compare-sync-ready")).toBeLessThan(events.lastIndexOf("jumpTo"));
    expect(beforeMap.snapshot()).toEqual({ center: [16, 62], zoom: 9.35, bearing: 0, pitch: 0 });
    expect(afterMap.snapshot()).toEqual(beforeMap.snapshot());
  });

  it("restores an existing snapshot without fitting or allowing a stale default", () => {
    const events: string[] = [];
    const beforeMap = fakeMap(events, 8);
    const afterMap = fakeMap(events, 8);
    const snapshot: CameraSnapshot = { center: [15.25, 61.75], zoom: 10.4, bearing: 2, pitch: 3 };

    applyCompareInitialCamera(events, beforeMap, afterMap, snapshot);

    expect(events).not.toContain("fitBounds");
    expect(beforeMap.snapshot()).toEqual(snapshot);
    expect(afterMap.snapshot()).toEqual(snapshot);
  });

  it("restores an existing snapshot without waiting for disturbance data", () => {
    const events: string[] = [];
    const beforeMap = fakeMap(events, 8);
    const afterMap = fakeMap(events, 8);
    const snapshot: CameraSnapshot = { center: [15.25, 61.75], zoom: 10.4, bearing: 2, pitch: 3 };
    const initializer = createCompareCameraInitializer(beforeMap, afterMap);

    expect(initializer.tryInitialize({ ...ready, initialCamera: snapshot })).toEqual(snapshot);
    expect(initializer.isInitialized()).toBe(true);
    expect(events).not.toContain("fitBounds");
  });

  it("is idempotent when duplicate readiness callbacks attempt initialization", () => {
    const events: string[] = [];
    const beforeMap = fakeMap(events);
    const afterMap = fakeMap(events);
    let initialized = false;
    const initialize = () => {
      if (initialized) return;
      applyCompareInitialCamera(events, beforeMap, afterMap, undefined);
      initialized = true;
    };

    initialize();
    const firstCamera = beforeMap.snapshot();
    initialize();

    expect(beforeMap.snapshot()).toEqual(firstCamera);
    expect(events.filter((event) => event === "compare-sync-ready")).toHaveLength(1);
  });
});
