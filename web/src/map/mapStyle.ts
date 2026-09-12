import type { StyleSpecification } from "maplibre-gl";

export const localMapStyle: StyleSpecification = {
  version: 8,
  name: "Landscape Disturbance Monitor — local canvas",
  sources: {},
  layers: [
    {
      id: "local-background",
      type: "background",
      paint: { "background-color": "#d9d2c5" },
    },
  ],
};
