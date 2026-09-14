import { describe, expect, it } from "vitest";
import type { DisturbanceCollection } from "../data/types";
import {
  fitInitialDisturbanceCamera,
  INITIAL_FIT_ZOOM_OFFSET,
  initialFitZoomOffsetForViewport,
  MAP_FIT_PADDING,
} from "./camera";

const disturbances: DisturbanceCollection = {
  type: "FeatureCollection",
  features: [
    {
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
    },
  ],
};

describe("shared initial camera", () => {
  it("uses disturbance bounds, a ready container size, and the configured desktop zoom offset", () => {
    const calls: Array<unknown> = [];
    const map = {
      resize: () => calls.push("resize"),
      fitBounds: (bounds: unknown, options: unknown) => calls.push({ bounds, options }),
      getZoom: () => 9,
      getContainer: () => ({ clientWidth: 1680 } as HTMLElement),
      jumpTo: (options: unknown) => calls.push({ jumpTo: options }),
      getBearing: () => 0,
      getPitch: () => 0,
    };

    fitInitialDisturbanceCamera(map, disturbances);

    expect(calls[0]).toBe("resize");
    expect(calls[1]).toEqual({
      bounds: [[14, 60], [18, 64]],
      options: { padding: MAP_FIT_PADDING, maxZoom: 11, duration: 0 },
    });
    expect(calls[2]).toEqual({ jumpTo: { center: [16, 62], zoom: 9 + INITIAL_FIT_ZOOM_OFFSET, bearing: 0, pitch: 0 } });
  });

  it("uses a lighter tightening policy on smaller map viewports", () => {
    expect(initialFitZoomOffsetForViewport(1680)).toBe(0.35);
    expect(initialFitZoomOffsetForViewport(1440)).toBe(0.35);
    expect(initialFitZoomOffsetForViewport(1200)).toBe(0.35);
    expect(initialFitZoomOffsetForViewport(1024)).toBe(0.35);
    expect(initialFitZoomOffsetForViewport(768)).toBe(0.2);
    expect(initialFitZoomOffsetForViewport(640)).toBe(0.2);
  });
});
