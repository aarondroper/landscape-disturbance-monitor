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

export function disturbanceLayers(mode: DisturbanceLayerMode = "recovery"): [FillLayerSpecification, LineLayerSpecification, LineLayerSpecification, LineLayerSpecification] {
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
          "#b19669",
          "#887f68",
        ],
        "fill-opacity": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          0.12,
          ["boolean", ["feature-state", "hover"], false],
          0.18,
          isDisturbanceMode ? 0.025 : 0.06,
        ],
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
          "#8b704d",
          "#625f50",
        ],
        "line-width": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          1,
          ["boolean", ["feature-state", "hover"], false],
          1.7,
          0.9,
        ],
        "line-opacity": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          0,
          ["boolean", ["feature-state", "hover"], false],
          0.9,
          isDisturbanceMode ? 0.18 : 0.58,
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
