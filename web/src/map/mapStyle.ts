import type { StyleSpecification } from "maplibre-gl";

export const MAP_CANVAS_BACKGROUND_COLOR = "#2b3733";
export const MAP_OVERLAY_SURFACE_COLOR = "#faf8f2";

export const localMapStyle: StyleSpecification = {
  version: 8,
  name: "Landscape Disturbance Monitor — local canvas",
  sources: {},
  layers: [
    {
      id: "local-background",
      type: "background",
      paint: { "background-color": MAP_CANVAS_BACKGROUND_COLOR },
    },
  ],
};
