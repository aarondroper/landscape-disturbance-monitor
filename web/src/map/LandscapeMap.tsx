import * as maplibregl from "maplibre-gl";
import type { MapLayerMouseEvent } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef } from "react";
import { cogProtocol } from "@geomatico/maplibre-cog-protocol";
import { assetUrl, calculateBounds, imageryPath } from "../data/loadData";
import type { DisturbanceCollection, DisturbanceProperties } from "../data/types";
import { localMapStyle } from "./mapStyle";

maplibregl.addProtocol("cog", cogProtocol);
maplibregl.setWorkerUrl(workerUrl);

interface LandscapeMapProps {
  disturbances: DisturbanceCollection;
  onSelect: (disturbance?: DisturbanceProperties) => void;
  onError: (message: string) => void;
}

const geojsonSourceId = "disturbances";
const fillLayerId = "disturbance-fill";
const outlineLayerId = "disturbance-outline";

export function LandscapeMap({ disturbances, onSelect, onError }: LandscapeMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | undefined>(undefined);
  const hoveredIdRef = useRef<string | undefined>(undefined);
  const selectedIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: localMapStyle,
      center: [15.5, 61.9],
      zoom: 8,
      pitch: 0,
      bearing: 0,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");

    const handleError = (event: maplibregl.ErrorEvent) => {
      const message = event.error instanceof Error ? event.error.message : String(event.error);
      onError(`Map data error: ${message}`);
    };
    map.on("error", handleError);
    map.on("load", () => {
      map.addSource("rgb-2018", {
        type: "raster",
        url: `cog://${assetUrl(imageryPath())}`,
        tileSize: 256,
      });
      map.addLayer({
        id: "rgb-2018-layer",
        source: "rgb-2018",
        type: "raster",
        paint: { "raster-opacity": 1, "raster-fade-duration": 0 },
      });
      map.addSource(geojsonSourceId, {
        type: "geojson",
        data: disturbances as never,
        promoteId: "disturbance_id",
      });
      map.addLayer({
        id: fillLayerId,
        source: geojsonSourceId,
        type: "fill",
        paint: {
          "fill-color": ["case", ["boolean", ["feature-state", "selected"], false], "#c3894c", ["boolean", ["feature-state", "hover"], false], "#b19669", "#887f68"],
          "fill-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.34, ["boolean", ["feature-state", "hover"], false], 0.2, 0.07],
        },
      });
      map.addLayer({
        id: outlineLayerId,
        source: geojsonSourceId,
        type: "line",
        paint: {
          "line-color": ["case", ["boolean", ["feature-state", "selected"], false], "#553e29", ["boolean", ["feature-state", "hover"], false], "#70583b", "#6a6655"],
          "line-width": ["case", ["boolean", ["feature-state", "selected"], false], 2.4, ["boolean", ["feature-state", "hover"], false], 1.8, 1],
          "line-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.95, ["boolean", ["feature-state", "hover"], false], 0.85, 0.68],
        },
      });

      const [west, south, east, north] = calculateBounds(disturbances);
      map.fitBounds([[west, south], [east, north]], {
        padding: { top: 96, right: 360, bottom: 72, left: 32 },
        maxZoom: 11,
        duration: 0,
      });

      const setHover = (event: MapLayerMouseEvent, hovered: boolean) => {
        const feature = event.features?.[0];
        if (!feature) return;
        const id = String(feature.properties?.disturbance_id ?? feature.id ?? "");
        if (!id) return;
        map.setFeatureState({ source: geojsonSourceId, id }, { hover: hovered });
        map.getCanvas().style.cursor = hovered ? "pointer" : "";
        if (hovered) hoveredIdRef.current = id;
        else if (hoveredIdRef.current === id) hoveredIdRef.current = undefined;
      };
      map.on("mouseenter", fillLayerId, (event: MapLayerMouseEvent) => setHover(event, true));
      map.on("mouseleave", fillLayerId, (event: MapLayerMouseEvent) => setHover(event, false));
      map.on("click", fillLayerId, (event: MapLayerMouseEvent) => {
        const feature = event.features?.[0];
        if (!feature) return;
        const id = String(feature.properties?.disturbance_id ?? feature.id ?? "");
        if (!id) return;
        if (selectedIdRef.current) {
          map.setFeatureState({ source: geojsonSourceId, id: selectedIdRef.current }, { selected: false });
        }
        map.setFeatureState({ source: geojsonSourceId, id }, { selected: true });
        selectedIdRef.current = id;
        const selected = disturbances.features.find((item) => item.properties.disturbance_id === id);
        onSelect(selected?.properties);
      });
      map.on("click", (event) => {
        if (map.queryRenderedFeatures(event.point, { layers: [fillLayerId] }).length === 0) {
          if (selectedIdRef.current) {
            map.setFeatureState({ source: geojsonSourceId, id: selectedIdRef.current }, { selected: false });
            selectedIdRef.current = undefined;
          }
          onSelect(undefined);
        }
      });
    });

    return () => {
      map.remove();
      mapRef.current = undefined;
    };
  }, [disturbances, onError, onSelect]);

  return <div ref={containerRef} className="map-canvas" aria-label="Interactive disturbance landscape map" />;
}
