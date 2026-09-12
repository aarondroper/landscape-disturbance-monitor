import { describe, expect, it, vi } from "vitest";
import {
  comparisonLabels,
  DISTURBANCE_FILL_LAYER_ID,
  DISTURBANCE_OUTLINE_LAYER_ID,
  DISTURBANCE_SOURCE_ID,
  disturbanceLayers,
  disturbanceSource,
  imagerySource,
  imagerySourceId,
  INITIAL_DIVIDER_PERCENT,
} from "./mapLayers";

describe("comparison map configuration", () => {
  it("uses the 2017 before and 2018 after RGB COG assets", () => {
    vi.stubGlobal("window", { location: { origin: "https://monitor.example" } });
    expect(imagerySource(2017)).toMatchObject({
      type: "raster",
      url: "cog://https://monitor.example/imagery/2017/rgb.tif",
      tileSize: 256,
    });
    expect(imagerySource(2018)).toMatchObject({
      type: "raster",
      url: "cog://https://monitor.example/imagery/2018/rgb.tif",
      tileSize: 256,
    });
    expect(imagerySourceId(2017)).toBe("rgb-2017");
    expect(imagerySourceId(2018)).toBe("rgb-2018");
    vi.unstubAllGlobals();
  });

  it("starts the vertical divider at 50% and keeps compact year labels", () => {
    expect(INITIAL_DIVIDER_PERCENT).toBe(50);
    expect(comparisonLabels).toEqual({
      before: { year: 2017, descriptor: "PRE-DISTURBANCE" },
      after: { year: 2018, descriptor: "POST-DISTURBANCE" },
    });
  });

  it("uses one promoted disturbance source and identical layers for both maps", () => {
    const source = disturbanceSource({ type: "FeatureCollection", features: [] });
    expect(source).toMatchObject({ type: "geojson", promoteId: "disturbance_id" });
    expect(source).not.toHaveProperty("url");
    expect(disturbanceLayers().map((layer) => layer.id)).toEqual([
      DISTURBANCE_FILL_LAYER_ID,
      DISTURBANCE_OUTLINE_LAYER_ID,
    ]);
    expect(DISTURBANCE_SOURCE_ID).toBe("disturbances");
    expect(JSON.stringify({ source, layers: disturbanceLayers() })).not.toMatch(/2020|2023|2026|nbr|recovery|dnbr/i);
  });

  it("does not reference external style URLs or API keys", () => {
    expect(JSON.stringify(disturbanceLayers())).not.toMatch(/https?:\/\//);
    expect(JSON.stringify(disturbanceLayers())).not.toMatch(/api[_-]?key|access[_-]?token/i);
  });
});
