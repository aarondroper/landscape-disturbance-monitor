import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import {
  comparisonLabels,
  DISTURBANCE_CASING_LAYER_ID,
  DISTURBANCE_HOVER_COLOR,
  DISTURBANCE_NORMAL_CASING_COLOR,
  DISTURBANCE_NORMAL_CASING_OPACITY,
  DISTURBANCE_NORMAL_CASING_WIDTH,
  DISTURBANCE_NORMAL_COLOR,
  DISTURBANCE_NORMAL_FILL_OPACITY,
  DISTURBANCE_NORMAL_LINE_OPACITY,
  DISTURBANCE_NORMAL_LINE_WIDTH,
  DISTURBANCE_FILL_LAYER_ID,
  DISTURBANCE_RASTER_LAYER_ID,
  DISTURBANCE_RASTER_SOURCE_ID,
  DISTURBANCE_OUTLINE_LAYER_ID,
  DISTURBANCE_SELECTED_HALO_LAYER_ID,
  DISTURBANCE_SELECTED_OUTLINE_LAYER_ID,
  DISTURBANCE_VECTOR_LAYER_IDS,
  DISTURBANCE_SOURCE_ID,
  DISTURBANCE_BACKGROUND_OPACITY,
  DISTURBANCE_RASTER_OPACITY,
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
  setDisturbanceLayersVisible,
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

  it("uses one promoted disturbance source and shared layer ids for both maps", () => {
    const source = disturbanceSource({ type: "FeatureCollection", features: [] });
    expect(source).toMatchObject({ type: "geojson", promoteId: "disturbance_id" });
    expect(source).not.toHaveProperty("url");
    expect(disturbanceLayers().map((layer) => layer.id)).toEqual([
      DISTURBANCE_FILL_LAYER_ID,
      DISTURBANCE_CASING_LAYER_ID,
      DISTURBANCE_OUTLINE_LAYER_ID,
      DISTURBANCE_SELECTED_HALO_LAYER_ID,
      DISTURBANCE_SELECTED_OUTLINE_LAYER_ID,
    ]);
    expect(DISTURBANCE_SOURCE_ID).toBe("disturbances");
    expect(JSON.stringify({ source, layers: disturbanceLayers() })).not.toMatch(/2020|2023|2026|nbr|recovery|dnbr/i);
  });

  it("toggles only the five disturbance vector layers", () => {
    const layoutCalls: Array<{ id: string; visibility: string }> = [];
    const map = {
      getLayer: (id: string) => id === DISTURBANCE_FILL_LAYER_ID || id === DISTURBANCE_OUTLINE_LAYER_ID ? {} : undefined,
      setLayoutProperty: (id: string, _property: "visibility", visibility: "visible" | "none") => layoutCalls.push({ id, visibility }),
    };
    setDisturbanceLayersVisible(map, false);
    expect(layoutCalls).toEqual([
      { id: DISTURBANCE_FILL_LAYER_ID, visibility: "none" },
      { id: DISTURBANCE_OUTLINE_LAYER_ID, visibility: "none" },
    ]);
    expect(DISTURBANCE_VECTOR_LAYER_IDS).toHaveLength(5);
    setDisturbanceLayersVisible({ getLayer: () => ({}), setLayoutProperty: map.setLayoutProperty }, true);
    expect(layoutCalls.slice(-5).every(({ visibility }) => visibility === "visible")).toBe(true);
  });

  it("keeps a clear normal, hover, and selected visual hierarchy", () => {
    const [fill, casing, outline, halo, selectedOutline] = disturbanceLayers();
    const fillOpacity = fill.paint?.["fill-opacity"] as unknown[];
    const fillColor = fill.paint?.["fill-color"] as unknown[];
    const casingWidth = casing.paint?.["line-width"] as unknown[];
    const casingOpacity = casing.paint?.["line-opacity"] as unknown[];
    const outlineWidth = outline.paint?.["line-width"] as unknown[];
    const outlineOpacity = outline.paint?.["line-opacity"] as unknown[];
    const haloWidth = halo.paint?.["line-width"] as unknown[];
    const selectedWidth = selectedOutline.paint?.["line-width"] as unknown[];

    expect(fillColor.at(-1)).toBe(DISTURBANCE_NORMAL_COLOR);
    expect(fillColor.at(-1)).not.toBe("#ff0000");
    expect(fillOpacity).toEqual(["case", ["boolean", ["feature-state", "selected"], false], 0.12, ["boolean", ["feature-state", "hover"], false], 0.18, DISTURBANCE_NORMAL_FILL_OPACITY]);
    expect(casing.id).toBe(DISTURBANCE_CASING_LAYER_ID);
    expect(casing.paint?.["line-color"]).toBe(DISTURBANCE_NORMAL_CASING_COLOR);
    expect(casingWidth.at(-1)).toBe(DISTURBANCE_NORMAL_CASING_WIDTH);
    expect(casingOpacity.at(-1)).toBe(DISTURBANCE_NORMAL_CASING_OPACITY);
    expect(outline.paint?.["line-color"]).toEqual(["case", ["boolean", ["feature-state", "selected"], false], "#625f50", ["boolean", ["feature-state", "hover"], false], DISTURBANCE_HOVER_COLOR, DISTURBANCE_NORMAL_COLOR]);
    expect(outlineWidth.at(-1)).toBe(DISTURBANCE_NORMAL_LINE_WIDTH);
    expect(outlineWidth.at(-2)).toBe(1.7);
    expect(outlineOpacity.at(-1)).toBe(DISTURBANCE_NORMAL_LINE_OPACITY);
    expect(outlineOpacity.at(-2)).toBe(0.9);
    expect(outlineWidth.at(-2)).toBeGreaterThan(outlineWidth.at(-1) as number);
    expect(outlineOpacity.at(-2)).toBeGreaterThan(outlineOpacity.at(-1) as number);
    expect(DISTURBANCE_NORMAL_COLOR).not.toBe("#ff0000");
    expect(haloWidth.at(-2)).toBe(3);
    expect(selectedWidth.at(-2)).toBe(1.7);
    expect(halo.paint?.["line-color"]).toBe("#202c29");
    expect(halo.paint?.["line-opacity"]).toEqual(["case", ["boolean", ["feature-state", "selected"], false], 0.82, 0]);
    expect(selectedOutline.paint?.["line-color"]).toBe("#d8d9cb");
    expect(selectedOutline.paint?.["line-opacity"]).toEqual(["case", ["boolean", ["feature-state", "selected"], false], 0.94, 0]);
  });

  it("subdues unselected polygons only in Disturbance mode", () => {
    const [disturbanceFill, disturbanceCasing, disturbanceOutline] = disturbanceLayers("disturbance");
    const [recoveryFill, recoveryCasing, recoveryOutline] = disturbanceLayers("recovery");
    const disturbanceFillOpacity = disturbanceFill.paint?.["fill-opacity"] as unknown[];
    const disturbanceCasingOpacity = disturbanceCasing.paint?.["line-opacity"] as unknown[];
    const recoveryFillOpacity = recoveryFill.paint?.["fill-opacity"] as unknown[];
    const recoveryCasingOpacity = recoveryCasing.paint?.["line-opacity"] as unknown[];
    expect(disturbanceFillOpacity.at(-1)).toBe(0.035);
    expect(disturbanceCasingOpacity.at(-1)).toBe(DISTURBANCE_NORMAL_CASING_OPACITY);
    expect(disturbanceOutline.paint?.["line-color"]).toEqual(recoveryOutline.paint?.["line-color"]);
    expect(disturbanceOutline.paint?.["line-opacity"]).toEqual(recoveryOutline.paint?.["line-opacity"]);
    expect(disturbanceCasingOpacity).toEqual(recoveryCasingOpacity);
    expect(disturbanceFillOpacity.slice(0, -1)).toEqual(recoveryFillOpacity.slice(0, -1));
    expect(disturbanceOutline.paint?.["line-opacity"]).not.toContain(0.18);
  });

  it("keeps selected styling unmistakable without using pure white", () => {
    const [, , , halo, selectedOutline] = disturbanceLayers();
    expect(halo.id).toBe(DISTURBANCE_SELECTED_HALO_LAYER_ID);
    expect(selectedOutline.id).toBe(DISTURBANCE_SELECTED_OUTLINE_LAYER_ID);
    expect(selectedOutline.paint?.["line-color"]).not.toBe("#ffffff");
    expect(selectedOutline.paint?.["line-color"]).not.toBe("#fff");
    expect(selectedOutline.paint?.["line-width"]).toEqual(["case", ["boolean", ["feature-state", "selected"], false], 1.7, 0]);
  });

  it("lets selected styling win when hover and selected state coexist", () => {
    const [fill, , outline, halo, selectedOutline] = disturbanceLayers();
    const fillColor = fill.paint?.["fill-color"] as unknown[];
    const outlineColor = outline.paint?.["line-color"] as unknown[];
    expect(fillColor[0]).toBe("case");
    expect(fillColor[1]).toEqual(["boolean", ["feature-state", "selected"], false]);
    expect(fillColor[3]).toEqual(["boolean", ["feature-state", "hover"], false]);
    expect(outlineColor[1]).toEqual(["boolean", ["feature-state", "selected"], false]);
    expect(outlineColor[3]).toEqual(["boolean", ["feature-state", "hover"], false]);
    expect(outline.paint?.["line-opacity"]).toEqual(["case", ["boolean", ["feature-state", "selected"], false], 0, ["boolean", ["feature-state", "hover"], false], 0.9, DISTURBANCE_NORMAL_LINE_OPACITY]);
    expect([fill, outline, halo, selectedOutline].map((layer) => layer.id)).toEqual([
      DISTURBANCE_FILL_LAYER_ID,
      DISTURBANCE_OUTLINE_LAYER_ID,
      DISTURBANCE_SELECTED_HALO_LAYER_ID,
      DISTURBANCE_SELECTED_OUTLINE_LAYER_ID,
    ]);
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
    expect(disturbanceRasterLayer().paint["raster-opacity"]).toBe(DISTURBANCE_RASTER_OPACITY);
    expect(disturbanceBackgroundLayer().paint["raster-opacity"]).toBe(DISTURBANCE_BACKGROUND_OPACITY);
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
    expect(disturbanceBackgroundLayer().paint["raster-opacity"]).toBe(DISTURBANCE_BACKGROUND_OPACITY);
  });
});
