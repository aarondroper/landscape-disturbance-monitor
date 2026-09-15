import type {
  FillLayerSpecification,
  GeoJSONSourceSpecification,
  LineLayerSpecification,
  RasterSourceSpecification,
} from "maplibre-gl";
import { AFTER_IMAGERY_YEAR, BEFORE_IMAGERY_YEAR, disturbancePath, imageryPath, recoveryPath } from "../data/loadData";
import { assetUrl } from "../data/assetUrl";
import type { DisturbanceCollection } from "../data/types";

export const INITIAL_DIVIDER_PERCENT = 50;
export const DISTURBANCE_SOURCE_ID = "disturbances";
export const DISTURBANCE_FILL_LAYER_ID = "disturbance-fill";
export const DISTURBANCE_CASING_LAYER_ID = "disturbance-casing";
export const DISTURBANCE_OUTLINE_LAYER_ID = "disturbance-outline";
export const DISTURBANCE_SELECTED_HALO_LAYER_ID = "disturbance-selected-halo";
export const DISTURBANCE_SELECTED_OUTLINE_LAYER_ID = "disturbance-selected-outline";
export const RECOVERY_BACKGROUND_SOURCE_ID = "recovery-reference-2018";
export const RECOVERY_BACKGROUND_LAYER_ID = "recovery-reference-2018-layer";
export const DISTURBANCE_RASTER_SOURCE_ID = "dnbr-2017-2018";
export const DISTURBANCE_RASTER_LAYER_ID = "dnbr-2017-2018-layer";
export const DISTURBANCE_BACKGROUND_OPACITY = 0.24;
export const DISTURBANCE_RASTER_OPACITY = 0.96;
export const RECOVERY_BACKGROUND_OPACITY = 0.52;
export const RECOVERY_LAYER_OPACITY = 0.95;
export const DISTURBANCE_NORMAL_COLOR = "#b9574f";
export const DISTURBANCE_HOVER_COLOR = "#c97968";
export const DISTURBANCE_NORMAL_CASING_COLOR = "#252c29";
export const DISTURBANCE_NORMAL_CASING_WIDTH = 2;
export const DISTURBANCE_NORMAL_CASING_OPACITY = 0.52;
export const DISTURBANCE_NORMAL_LINE_WIDTH = 1.15;
export const DISTURBANCE_NORMAL_LINE_OPACITY = 0.88;
export const DISTURBANCE_NORMAL_FILL_OPACITY = 0.06;

export const DISTURBANCE_VECTOR_LAYER_IDS = [
  DISTURBANCE_FILL_LAYER_ID,
  DISTURBANCE_CASING_LAYER_ID,
  DISTURBANCE_OUTLINE_LAYER_ID,
  DISTURBANCE_SELECTED_HALO_LAYER_ID,
  DISTURBANCE_SELECTED_OUTLINE_LAYER_ID,
] as const;

interface DisturbanceLayerVisibilityMap {
  getLayer: (layerId: string) => unknown;
  setLayoutProperty: (layerId: string, property: "visibility", value: "visible" | "none") => void;
}

export function setDisturbanceLayersVisible(map: DisturbanceLayerVisibilityMap, visible: boolean): void {
  const visibility = visible ? "visible" : "none";
  for (const layerId of DISTURBANCE_VECTOR_LAYER_IDS) {
    if (map.getLayer(layerId)) map.setLayoutProperty(layerId, "visibility", visibility);
  }
}

export const comparisonLabels = {
  before: { year: BEFORE_IMAGERY_YEAR, descriptor: "PRE-DISTURBANCE" },
  after: { year: AFTER_IMAGERY_YEAR, descriptor: "POST-DISTURBANCE" },
} as const;

export function imagerySourceId(year: number): string {
  return `rgb-${year}`;
}

export function imagerySource(year: number): RasterSourceSpecification {
  return {
    type: "raster",
    url: `cog://${assetUrl(imageryPath(year))}`,
    tileSize: 256,
  };
}

export function recoverySourceId(year: number): string {
  return `recovery-${year}`;
}

export function recoveryLayerId(year: number): string {
  return `${recoverySourceId(year)}-layer`;
}

export function recoveryCogUrl(year: number): string {
  return assetUrl(recoveryPath(year));
}

export function recoverySource(year: number): RasterSourceSpecification {
  return {
    type: "raster",
    url: `cog://${recoveryCogUrl(year)}`,
    tileSize: 256,
  };
}

export function disturbanceCogUrl(): string {
  return assetUrl(disturbancePath());
}

export function dnbrSource(): RasterSourceSpecification {
  return {
    type: "raster",
    url: `cog://${disturbanceCogUrl()}`,
    tileSize: 256,
  };
}

export function disturbanceRasterLayer() {
  return {
    id: DISTURBANCE_RASTER_LAYER_ID,
    source: DISTURBANCE_RASTER_SOURCE_ID,
    type: "raster" as const,
    paint: { "raster-opacity": DISTURBANCE_RASTER_OPACITY, "raster-fade-duration": 0 },
  };
}

export function disturbanceBackgroundLayer() {
  return {
    id: "disturbance-reference-2018-layer",
    source: "disturbance-reference-2018",
    type: "raster" as const,
    paint: { "raster-opacity": DISTURBANCE_BACKGROUND_OPACITY, "raster-fade-duration": 0 },
  };
}

export function recoveryBackgroundLayer(): {
  id: string;
  source: string;
  type: "raster";
  paint: { "raster-opacity": number; "raster-fade-duration": number };
} {
  return {
    id: RECOVERY_BACKGROUND_LAYER_ID,
    source: RECOVERY_BACKGROUND_SOURCE_ID,
    type: "raster",
    paint: { "raster-opacity": RECOVERY_BACKGROUND_OPACITY, "raster-fade-duration": 0 },
  };
}

export function recoveryLayer(year: number) {
  return {
    id: recoveryLayerId(year),
    source: recoverySourceId(year),
    type: "raster" as const,
    paint: { "raster-opacity": RECOVERY_LAYER_OPACITY, "raster-fade-duration": 0 },
  };
}

export function disturbanceSource(disturbances: DisturbanceCollection): GeoJSONSourceSpecification {
  return {
    type: "geojson",
    data: disturbances as never,
    promoteId: "disturbance_id",
  };
}

export type DisturbanceLayerMode = "disturbance" | "recovery";

export function disturbanceLayers(mode: DisturbanceLayerMode = "recovery"): [FillLayerSpecification, LineLayerSpecification, LineLayerSpecification, LineLayerSpecification, LineLayerSpecification] {
  const isDisturbanceMode = mode === "disturbance";

  return [
    {
      id: DISTURBANCE_FILL_LAYER_ID,
      source: DISTURBANCE_SOURCE_ID,
      type: "fill",
      paint: {
        "fill-color": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          "#d1dacb",
          ["boolean", ["feature-state", "hover"], false],
          DISTURBANCE_HOVER_COLOR,
          DISTURBANCE_NORMAL_COLOR,
        ],
        "fill-opacity": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          0.12,
          ["boolean", ["feature-state", "hover"], false],
          0.18,
          isDisturbanceMode ? 0.035 : DISTURBANCE_NORMAL_FILL_OPACITY,
        ],
      },
    },
    {
      id: DISTURBANCE_CASING_LAYER_ID,
      source: DISTURBANCE_SOURCE_ID,
      type: "line",
      paint: {
        "line-color": DISTURBANCE_NORMAL_CASING_COLOR,
        "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 0, DISTURBANCE_NORMAL_CASING_WIDTH],
        "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0, DISTURBANCE_NORMAL_CASING_OPACITY],
      },
    },
    {
      id: DISTURBANCE_OUTLINE_LAYER_ID,
      source: DISTURBANCE_SOURCE_ID,
      type: "line",
      paint: {
        "line-color": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          "#625f50",
          ["boolean", ["feature-state", "hover"], false],
          DISTURBANCE_HOVER_COLOR,
          DISTURBANCE_NORMAL_COLOR,
        ],
        "line-width": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          1,
          ["boolean", ["feature-state", "hover"], false],
          1.7,
          DISTURBANCE_NORMAL_LINE_WIDTH,
        ],
        "line-opacity": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          0,
          ["boolean", ["feature-state", "hover"], false],
          0.9,
          DISTURBANCE_NORMAL_LINE_OPACITY,
        ],
      },
    },
    {
      id: DISTURBANCE_SELECTED_HALO_LAYER_ID,
      source: DISTURBANCE_SOURCE_ID,
      type: "line",
      paint: {
        "line-color": "#202c29",
        "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 3, 0],
        "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.82, 0],
        "line-blur": 0.45,
      },
    },
    {
      id: DISTURBANCE_SELECTED_OUTLINE_LAYER_ID,
      source: DISTURBANCE_SOURCE_ID,
      type: "line",
      paint: {
        "line-color": "#d8d9cb",
        "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 1.7, 0],
        "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.94, 0],
        "line-blur": 0.1,
      },
    },
  ];
}
