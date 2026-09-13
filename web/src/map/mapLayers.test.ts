import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import {
  comparisonLabels,
  DISTURBANCE_FILL_LAYER_ID,
  DISTURBANCE_RASTER_LAYER_ID,
  DISTURBANCE_RASTER_SOURCE_ID,
  DISTURBANCE_OUTLINE_LAYER_ID,
  DISTURBANCE_SOURCE_ID,
  disturbanceLayers,
  disturbanceRasterLayer,
  disturbanceBackgroundLayer,
  dnbrSource,
  disturbanceCogUrl,
  disturbanceSource,
  imagerySource,
  imagerySourceId,
  INITIAL_DIVIDER_PERCENT,
  RECOVERY_BACKGROUND_OPACITY,
  RECOVERY_LAYER_OPACITY,
  recoveryBackgroundLayer,
  recoveryLayer,
} from "./mapLayers";
import { MAP_FIT_PADDING } from "./camera";
import { RECOVERY_ALPHA, RECOVERY_COLOR_STOPS } from "./recoveryColor";

describe("comparison map configuration", () => {
  it("uses the 2017 before and 2018 after RGB COG assets", () => {
    vi.stubGlobal("window", { location: { origin: "https://monitor.example" } });
    expect(imagerySource(2017)).toMatchObject({
      type: "raster",
      url: "cog://https://monitor.example/geo/imagery/2017/rgb.tif",
      tileSize: 256,
    });
    expect(imagerySource(2018)).toMatchObject({
      type: "raster",
      url: "cog://https://monitor.example/geo/imagery/2018/rgb.tif",
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

describe("fixed spectral-change map configuration", () => {
  it("loads exactly one fixed dNBR browser COG with origin-aware URL construction", () => {
    vi.stubGlobal("window", { location: { origin: "https://monitor.example" } });
    expect(disturbanceCogUrl()).toBe("https://monitor.example/geo/rasters/change/dnbr-2017-2018.tif");
    expect(dnbrSource()).toMatchObject({
      type: "raster",
      url: "cog://https://monitor.example/geo/rasters/change/dnbr-2017-2018.tif",
      tileSize: 256,
    });
    expect(disturbanceRasterLayer()).toMatchObject({ id: DISTURBANCE_RASTER_LAYER_ID, source: DISTURBANCE_RASTER_SOURCE_ID, type: "raster" });
    expect(disturbanceBackgroundLayer().paint["raster-opacity"]).toBe(0.38);
    expect(JSON.stringify({ source: dnbrSource(), layer: disturbanceRasterLayer() })).not.toMatch(/rasters\/(nbr|recovery)\//i);
    vi.unstubAllGlobals();
  });

  it("does not add annual dNBR alternatives or a raster-pixel inspector", () => {
    expect(JSON.stringify({ path: "rasters/change/dnbr-2017-2018.tif", layer: disturbanceRasterLayer() })).not.toMatch(/2019|2020|2021|2022|2023|2024|2025|2026|pixel/i);
  });

  it("keeps burn-severity terminology out of the Disturbance UI/config", () => {
    const source = readFileSync(new URL("./DisturbanceMap.tsx", import.meta.url), "utf8");
    expect(source).not.toMatch(/burn[- ]?severity|severity/i);
    expect(source).not.toMatch(/type=["']range["']|recovery-coverage|rasters\/nbr/i);
  });
});

describe("shared visual framing and Recovery display configuration", () => {
  it("uses one modest fit padding across all map modes", () => {
    expect(MAP_FIT_PADDING).toEqual({ top: 88, right: 24, bottom: 64, left: 24 });
  });

  it("strengthens Recovery context without changing its data source", () => {
    expect(recoveryBackgroundLayer().paint["raster-opacity"]).toBe(RECOVERY_BACKGROUND_OPACITY);
    expect(RECOVERY_BACKGROUND_OPACITY).toBe(0.52);
    expect(recoveryLayer(2026).paint["raster-opacity"]).toBe(RECOVERY_LAYER_OPACITY);
    expect(RECOVERY_LAYER_OPACITY).toBe(0.95);
    expect(RECOVERY_ALPHA).toBe(232);
    expect(RECOVERY_COLOR_STOPS.map(({ value }) => value)).toEqual([0, 0.5, 1, 1.5]);
    expect(RECOVERY_COLOR_STOPS[0].value).toBeLessThan(RECOVERY_COLOR_STOPS[1].value);
    expect(RECOVERY_COLOR_STOPS[1].value).toBeLessThan(RECOVERY_COLOR_STOPS[2].value);
    expect(RECOVERY_COLOR_STOPS[2].value).toBeLessThan(RECOVERY_COLOR_STOPS[3].value);
  });

  it("preserves the fixed Disturbance context opacity", () => {
    expect(disturbanceBackgroundLayer().paint["raster-opacity"]).toBe(0.38);
  });
});
