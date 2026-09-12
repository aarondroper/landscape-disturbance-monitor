import type {
  FillLayerSpecification,
  GeoJSONSourceSpecification,
  LineLayerSpecification,
  RasterSourceSpecification,
} from "maplibre-gl";
import { AFTER_IMAGERY_YEAR, BEFORE_IMAGERY_YEAR, assetUrl, imageryPath } from "../data/loadData";
import type { DisturbanceCollection } from "../data/types";

export const INITIAL_DIVIDER_PERCENT = 50;
export const DISTURBANCE_SOURCE_ID = "disturbances";
export const DISTURBANCE_FILL_LAYER_ID = "disturbance-fill";
export const DISTURBANCE_OUTLINE_LAYER_ID = "disturbance-outline";

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

export function disturbanceSource(disturbances: DisturbanceCollection): GeoJSONSourceSpecification {
  return {
    type: "geojson",
    data: disturbances as never,
    promoteId: "disturbance_id",
  };
}

export function disturbanceLayers(): [FillLayerSpecification, LineLayerSpecification] {
  return [
    {
      id: DISTURBANCE_FILL_LAYER_ID,
      source: DISTURBANCE_SOURCE_ID,
      type: "fill",
      paint: {
        "fill-color": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          "#c3894c",
          ["boolean", ["feature-state", "hover"], false],
          "#b19669",
          "#887f68",
        ],
        "fill-opacity": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          0.34,
          ["boolean", ["feature-state", "hover"], false],
          0.2,
          0.07,
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
          "#553e29",
          ["boolean", ["feature-state", "hover"], false],
          "#70583b",
          "#6a6655",
        ],
        "line-width": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          2.4,
          ["boolean", ["feature-state", "hover"], false],
          1.8,
          1,
        ],
        "line-opacity": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          0.95,
          ["boolean", ["feature-state", "hover"], false],
          0.85,
          0.68,
        ],
      },
    },
  ];
}
