import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { MAP_VIEW_MODES } from "./map/viewMode";

const appSource = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const headerSource = readFileSync(new URL("./components/AppHeader.tsx", import.meta.url), "utf8");
const inspectorSource = readFileSync(new URL("./components/InspectorPanel.tsx", import.meta.url), "utf8");
const compareSource = readFileSync(new URL("./map/LandscapeCompareMap.tsx", import.meta.url), "utf8");
const disturbanceSource = readFileSync(new URL("./map/DisturbanceMap.tsx", import.meta.url), "utf8");
const recoverySource = readFileSync(new URL("./map/RecoveryMap.tsx", import.meta.url), "utf8");
const cssSource = readFileSync(new URL("./styles/app.css", import.meta.url), "utf8");

describe("integrated application shell contract", () => {
  it("exposes a desktop rail, map stage, and inspector grid", () => {
    expect(appSource).toContain('className="app-layout"');
    expect(appSource).toContain('className="map-stage"');
    expect(headerSource).toContain('className="app-sidebar"');
    expect(inspectorSource).toContain('className="inspector-panel"');
    expect(cssSource).toContain("grid-template-columns: var(--rail-width) minmax(0, 1fr) var(--inspector-width)");
    expect(cssSource).toContain("@media (min-width: 1100px)");
  });

  it("keeps the brand slot, project metadata, and exactly three modes in the rail", () => {
    expect(headerSource).toContain('className="app-logo brand-mark"');
    expect(headerSource).toContain("Hälsingland, Sweden · 2017–2026");
    expect(headerSource).toContain("Sentinel-2 disturbance &amp; spectral recovery");
    expect(headerSource).toContain("Methodology");
    expect(headerSource).toContain("MAP_VIEW_MODES.map");
    expect(MAP_VIEW_MODES).toEqual(["compare", "disturbance", "recovery"]);
  });

  it("keeps the unified inspector content and neutral initial selection", () => {
    expect(appSource).toContain("<InspectorPanel");
    expect(inspectorSource).toContain("recovery-year-control");
    expect(inspectorSource).toContain("recovery-legend");
    expect(inspectorSource).toContain("Selected area coverage");
    expect(inspectorSource).toContain("<DisturbanceDetails");
    expect(appSource).toContain("useState<DisturbanceProperties>()");
    expect(appSource).not.toContain('"disturbance-002"');
  });

  it("contains map overlays inside their map roots", () => {
    expect(compareSource).toContain('className="comparison-map"');
    expect(compareSource).toContain('className="comparison-hint"');
    expect(compareSource).toContain("comparisonLabels.before");
    expect(compareSource).toContain("comparisonLabels.after");
    expect(disturbanceSource).toContain('className="disturbance-legend"');
    expect(disturbanceSource).toContain('className="disturbance-label"');
    expect(disturbanceSource).toContain('className="disturbance-background-label"');
    expect(recoverySource).toContain('className="recovery-label"');
    expect(recoverySource).toContain('className="recovery-background-label"');
    expect(cssSource).toContain(".comparison-map, .disturbance-map, .recovery-map, .map-placeholder { inset: 0; border: 0; border-radius: 0; box-shadow: none; }");
    expect(cssSource).toContain("--map-top-badge-height: 44px");
    expect(cssSource).toContain("--map-control-top: calc(var(--map-overlay-inset) + var(--map-top-badge-height) + var(--map-control-gap));");
    expect(cssSource).toContain("@media (min-width: 901px) and (max-width: 1099px)");
    expect(cssSource).toContain("right: calc(var(--inspector-width) + var(--map-overlay-inset) + var(--map-control-gap));");
  });

  it("keeps map controls within the central stage and preserves accessible controls", () => {
    expect(compareSource).toContain('new maplibregl.NavigationControl');
    expect(compareSource).toContain('new maplibregl.ScaleControl');
    expect(compareSource).toContain('swiper.setAttribute("role", "slider")');
    expect(cssSource).toContain(".map-stage { position: relative");
    expect(cssSource).toContain(".maplibregl-ctrl-top-right .maplibregl-ctrl");
    expect(cssSource).toContain(".maplibregl-ctrl-bottom-right .maplibregl-ctrl");
    expect(cssSource).toContain(".maplibregl-ctrl-attrib");
  });

  it("shares the dark canvas style across Compare, Disturbance, and Recovery", () => {
    expect(compareSource.match(/style: localMapStyle/g)).toHaveLength(2);
    expect(disturbanceSource).toContain("style: localMapStyle");
    expect(recoverySource).toContain("style: localMapStyle");
    expect(cssSource).toContain("--map-canvas-bg: #2b3733");
  });

  it("preserves analytical layers, palettes, and shared camera constraints", () => {
    expect(disturbanceSource).toContain("disturbanceColorFunction");
    expect(recoverySource).toContain("recoveryColorFunction");
    expect(recoverySource).toContain("pitch: initialCameraRef.current?.pitch ?? 0");
    expect(recoverySource).toContain("bearing: initialCameraRef.current?.bearing ?? 0");
    expect(compareSource).toContain("pitch: 0");
    expect(compareSource).toContain("bearing: 0");
    expect(cssSource).toContain("#466f6b 0%");
    expect(cssSource).toContain("#2f6f68 100%");
  });

  it("retains the responsive fallback for smaller screens", () => {
    expect(cssSource).toContain("@media (max-width: 720px)");
    expect(cssSource).toContain(".inspector-panel { top: auto; right: 12px; bottom: 68px");
    expect(cssSource).toContain(".app-sidebar { top: 12px; left: 12px");
    expect(cssSource).toContain(".mode-switch { display: flex; width: 100%; }");
  });
});
