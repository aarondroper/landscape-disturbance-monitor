import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { MAP_VIEW_MODES } from "../map/viewMode";

const appSource = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const inspectorSource = readFileSync(new URL("./InspectorPanel.tsx", import.meta.url), "utf8");
const detailsSource = readFileSync(new URL("./DisturbanceDetails.tsx", import.meta.url), "utf8");
const recoveryMapSource = readFileSync(new URL("../map/RecoveryMap.tsx", import.meta.url), "utf8");
const compareMapSource = readFileSync(new URL("../map/LandscapeCompareMap.tsx", import.meta.url), "utf8");
const disturbanceMapSource = readFileSync(new URL("../map/DisturbanceMap.tsx", import.meta.url), "utf8");
const mapLayersSource = readFileSync(new URL("../map/mapLayers.ts", import.meta.url), "utf8");
const cameraSource = readFileSync(new URL("../map/camera.ts", import.meta.url), "utf8");
const timelineSource = readFileSync(new URL("./RecoveryTimeline.tsx", import.meta.url), "utf8");
const cssSource = readFileSync(new URL("../styles/app.css", import.meta.url), "utf8");

describe("unified inspector contract", () => {
  it("uses one primary inspector and nests all Recovery sections inside it", () => {
    expect(appSource).toContain("<InspectorPanel");
    expect(appSource).not.toContain("<DisturbanceDetails");
    expect(inspectorSource).toContain('className="inspector-panel"');
    expect(inspectorSource.indexOf("<RecoveryInspector")).toBeLessThan(inspectorSource.indexOf("<DisturbanceDetails"));
    expect(inspectorSource).toContain('className="recovery-year-control"');
    expect(inspectorSource).toContain('className="recovery-legend"');
    expect(inspectorSource).toContain('className="recovery-coverage"');
    expect(recoveryMapSource).not.toContain("recovery-controls");
    expect(cssSource).not.toContain(".recovery-controls");
  });

  it("keeps the empty Recovery state concise and free of duplicate details", () => {
    expect(inspectorSource).toContain("isRecovery &&");
    expect(inspectorSource).toContain("showCoverage={!isRecovery}");
    expect(detailsSource).toContain("EMPTY_SELECTION_PRIMARY");
    expect(detailsSource).toContain("Select a disturbance area to inspect its spectral trajectory.");
  });

  it("preserves selected Recovery metrics, coverage context, and trajectory", () => {
    for (const label of ["Area", "2017 NBR", "2018 NBR", "2017–2018 dNBR", "2026 spectral recovery"]) {
      expect(detailsSource).toContain(label);
    }
    expect(inspectorSource).toContain("Selected area coverage");
    expect(detailsSource).toContain("<RecoveryTimeline");
  });

  it("keeps selected details connected to all three map modes", () => {
    expect(appSource.match(/selectedId=\{selected\?\.disturbance_id\}/g)).toHaveLength(3);
    expect(appSource).toContain('mapMode={mapMode}');
    expect(MAP_VIEW_MODES).toEqual(["compare", "disturbance", "recovery"]);
  });

  it("keeps the selected feature visibly configured in every map mode", () => {
    for (const mapSource of [compareMapSource, disturbanceMapSource, recoveryMapSource]) {
      expect(mapSource).toContain("disturbanceLayers(");
      expect(mapSource).toContain('map.getCanvas().style.cursor = id ? "pointer" : ""');
    }
    expect(compareMapSource).toContain('setMirroredFeatureState(maps, readyMaps, id, "hover", true)');
    expect(compareMapSource).toContain('replaceMirroredFeatureState(maps, readyMaps, selectedIdRef.current, id, "selected")');
    expect(disturbanceMapSource).toContain('"selected", false');
    expect(recoveryMapSource).toContain('"selected", false');
    expect(mapLayersSource).toContain("DISTURBANCE_SELECTED_HALO_LAYER_ID");
    expect(mapLayersSource).toContain("DISTURBANCE_SELECTED_OUTLINE_LAYER_ID");
  });

  it("keeps Compare labels and an accessible swipe hint with safe layout treatment", () => {
    expect(compareMapSource).toContain("comparisonLabels.before");
    expect(compareMapSource).toContain("comparisonLabels.after");
    expect(compareMapSource).toContain('className="comparison-hint"');
    expect(compareMapSource).not.toContain('className="comparison-hint" aria-hidden="true"');
    expect(cssSource).toContain("--rail-width: 312px");
    expect(cssSource).toContain("--inspector-width");
    expect(cssSource).toContain("--map-overlay-inset: 16px");
    expect(cssSource).toContain("--map-control-gap: 10px");
    expect(cssSource).toContain(".imagery-label--before { top: var(--map-overlay-inset); left: var(--map-overlay-inset); }");
    expect(cssSource).toContain(".maplibregl-ctrl-top-right { top: var(--map-control-top); right: 0; }");
    expect(cssSource).toContain(".maplibregl-ctrl-top-right { top: var(--map-overlay-inset); }");
  });

  it("keeps map framing and thematic display configuration in place", () => {
    expect(recoveryMapSource).toContain("fitInitialDisturbanceCamera(map, disturbances)");
    expect(disturbanceMapSource).toContain("fitInitialDisturbanceCamera(map, disturbances)");
    expect(compareMapSource).toContain("applyInitialCompareCamera(beforeMap, afterMap, disturbances, initialCameraRef.current)");
    expect(cameraSource).toContain("calculateBounds(disturbances)");
    expect(cameraSource).toContain("INITIAL_FIT_ZOOM_OFFSET = 0.35");
    expect(cameraSource).toContain("map.resize()");
    expect(cssSource).toContain("#6b4c3b 0%");
    expect(cssSource).toContain("#2f6f68 100%");
    expect(cssSource).toContain("#52736e 0%");
    expect(mapLayersSource).toContain("raster-opacity");
  });

  it("keeps the Recovery legend wording and trajectory labels intact", () => {
    for (const label of ["Below 2018 state", "Partway toward baseline", "2017 NBR baseline", "Above baseline"]) {
      expect(inspectorSource).toContain(label);
    }
    for (const label of ["2017 baseline", "Post-disturbance baseline", "NBR median", "Recovery median"]) {
      expect(timelineSource).toContain(label);
    }
  });

  it("guards map feature-state operations by explicit readiness in all modes", () => {
    expect(compareMapSource).toContain("readyMapsRef");
    expect(compareMapSource).toContain('map.once("load", handleLoad)');
    expect(compareMapSource).toContain("readyMaps.add(map)");
    expect(disturbanceMapSource).toContain("mapReadyRef");
    expect(recoveryMapSource).toContain("mapReadyRef");
    expect(disturbanceMapSource).toContain("selectedIdRef.current");
    expect(recoveryMapSource).toContain("selectedIdRef.current");
    expect(compareMapSource).toContain("setMirroredFeatureState");
    for (const mapSource of [compareMapSource, disturbanceMapSource, recoveryMapSource]) {
      expect(mapSource).not.toMatch(/map\.setFeatureState\(/);
    }
    expect(disturbanceMapSource).toContain("setDisturbanceFeatureState");
    expect(recoveryMapSource).toContain("setDisturbanceFeatureState");
  });

  it("keeps SVG layout constants numeric and preserves trajectory geometry", () => {
    expect(timelineSource).not.toContain('x="PLOT_LEFT"');
    expect(timelineSource.match(/x=\{PLOT_LEFT\}/g)).toHaveLength(5);
    expect(timelineSource).toContain("const PLOT_LEFT = 35;");
    expect(timelineSource).toContain("const PLOT_WIDTH = WIDTH - PLOT_LEFT - PLOT_RIGHT;");
  });

  it("keeps the initial selection neutral rather than implying analytical priority", () => {
    expect(appSource).toContain("useState<DisturbanceProperties>()");
    expect(appSource).not.toContain('"disturbance-002"');
  });
});
