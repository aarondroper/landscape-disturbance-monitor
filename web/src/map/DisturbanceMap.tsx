import * as maplibregl from "maplibre-gl";
import type { MapLayerMouseEvent, MapSourceDataEvent } from "maplibre-gl";
import { cogProtocol, setColorFunction } from "@geomatico/maplibre-cog-protocol";
import { useEffect, useRef, useState } from "react";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { AFTER_IMAGERY_YEAR, calculateBounds } from "../data/loadData";
import type { DisturbanceCollection, DisturbanceProperties } from "../data/types";
import { cameraSnapshotOf, MAP_FIT_PADDING, type CameraSnapshot } from "./camera";
import { disturbanceColorFunction } from "./disturbanceColor";
import {
  DISTURBANCE_FILL_LAYER_ID,
  DISTURBANCE_RASTER_SOURCE_ID,
  DISTURBANCE_SOURCE_ID,
  disturbanceBackgroundLayer,
  disturbanceRasterLayer,
  dnbrSource,
  disturbanceSource,
  disturbanceCogUrl,
  disturbanceLayers,
  imagerySource,
} from "./mapLayers";
import { setDisturbanceFeatureState } from "./interactionState";
import { localMapStyle } from "./mapStyle";

maplibregl.addProtocol("cog", cogProtocol);
maplibregl.setWorkerUrl(workerUrl);

interface DisturbanceMapProps {
  disturbances: DisturbanceCollection;
  selectedId?: string;
  initialCamera?: CameraSnapshot;
  onSelect: (disturbance?: DisturbanceProperties) => void;
  onError: (message: string) => void;
  onCameraChange: (camera: CameraSnapshot) => void;
}

export function DisturbanceMap({ disturbances, selectedId, initialCamera, onSelect, onError, onCameraChange }: DisturbanceMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const mapReadyRef = useRef(false);
  const selectedIdRef = useRef(selectedId);
  const hoveredIdRef = useRef<string | undefined>(undefined);
  const initialCameraRef = useRef(initialCamera);
  const [rasterLoaded, setRasterLoaded] = useState(false);

  useEffect(() => {
    const previousId = selectedIdRef.current;
    selectedIdRef.current = selectedId;
    const map = mapRef.current;
    if (!map) return;
    if (previousId && previousId !== selectedId) setDisturbanceFeatureState(map, previousId, "selected", false);
    if (selectedId) setDisturbanceFeatureState(map, selectedId, "selected", true);
  }, [selectedId]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let disposed = false;

    const map = new maplibregl.Map({
      container,
      style: localMapStyle,
      center: initialCameraRef.current?.center ?? [15.5, 61.9],
      zoom: initialCameraRef.current?.zoom ?? 8,
      bearing: initialCameraRef.current?.bearing ?? 0,
      pitch: initialCameraRef.current?.pitch ?? 0,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-right");

    const resizeObserver = new ResizeObserver(() => map.resize());
    resizeObserver.observe(container);
    const cogUrl = disturbanceCogUrl();
    setColorFunction(cogUrl, disturbanceColorFunction);

    const featureId = (event: MapLayerMouseEvent): string | undefined => {
      const feature = event.features?.[0];
      if (!feature) return undefined;
      const id = feature.properties?.disturbance_id ?? feature.id;
      return id === undefined ? undefined : String(id);
    };
    const updateHover = (id: string | undefined) => {
      const previousId = hoveredIdRef.current;
      if (previousId && previousId !== id) setDisturbanceFeatureState(map, previousId, "hover", false);
      if (id) setDisturbanceFeatureState(map, id, "hover", true);
      hoveredIdRef.current = id;
      map.getCanvas().style.cursor = id ? "pointer" : "";
    };
    const selectFeature = (id: string | undefined) => {
      const previousId = selectedIdRef.current;
      if (previousId && previousId !== id) setDisturbanceFeatureState(map, previousId, "selected", false);
      if (id) setDisturbanceFeatureState(map, id, "selected", true);
      selectedIdRef.current = id;
      onSelect(id ? disturbances.features.find((feature) => feature.properties.disturbance_id === id)?.properties : undefined);
    };
    const reportCamera = () => onCameraChange(cameraSnapshotOf(map));
    const handleMapError = () => {
      setRasterLoaded(true);
      onError("Unable to load disturbance data");
    };
    const markRasterLoaded = () => {
      if (map.isSourceLoaded(DISTURBANCE_RASTER_SOURCE_ID)) setRasterLoaded(true);
    };
    const handleSourceData = (event: MapSourceDataEvent) => {
      if (event.sourceId === DISTURBANCE_RASTER_SOURCE_ID && event.isSourceLoaded) setRasterLoaded(true);
    };

    map.on("error", handleMapError);
    map.on("moveend", reportCamera);
    map.on("sourcedata", handleSourceData);
    map.on("idle", markRasterLoaded);
    const handleLoad = () => {
      if (disposed) return;
      map.addSource("disturbance-reference-2018", imagerySource(AFTER_IMAGERY_YEAR));
      map.addLayer(disturbanceBackgroundLayer());
      map.addSource(DISTURBANCE_RASTER_SOURCE_ID, dnbrSource());
      map.addLayer(disturbanceRasterLayer());
      map.addSource(DISTURBANCE_SOURCE_ID, disturbanceSource(disturbances));
      for (const layer of disturbanceLayers("disturbance")) map.addLayer(layer);
      map.on("mouseenter", DISTURBANCE_FILL_LAYER_ID, (event: MapLayerMouseEvent) => updateHover(featureId(event)));
      map.on("mouseleave", DISTURBANCE_FILL_LAYER_ID, () => updateHover(undefined));
      map.on("click", DISTURBANCE_FILL_LAYER_ID, (event: MapLayerMouseEvent) => {
        const id = featureId(event);
        if (id) selectFeature(id);
      });
      map.on("click", (event) => {
        if (map.queryRenderedFeatures(event.point, { layers: [DISTURBANCE_FILL_LAYER_ID] }).length === 0) selectFeature(undefined);
      });
      if (!initialCameraRef.current) {
        const [west, south, east, north] = calculateBounds(disturbances);
        map.fitBounds([[west, south], [east, north]], { padding: MAP_FIT_PADDING, maxZoom: 11, duration: 0 });
      }
      markMapReady();
    };
    const markMapReady = () => {
      if (disposed) return;
      if (!map.isStyleLoaded() || !map.getSource(DISTURBANCE_SOURCE_ID)) return;
      mapReadyRef.current = true;
      if (selectedIdRef.current) setDisturbanceFeatureState(map, selectedIdRef.current, "selected", true);
    };
    map.on("styledata", markMapReady);
    map.once("load", handleLoad);

    return () => {
      disposed = true;
      resizeObserver.disconnect();
      map.off("load", handleLoad);
      map.off("styledata", markMapReady);
      map.off("error", handleMapError);
      map.off("moveend", reportCamera);
      map.off("sourcedata", handleSourceData);
      map.off("idle", markRasterLoaded);
      mapReadyRef.current = false;
      hoveredIdRef.current = undefined;
      mapRef.current = null;
      map.remove();
      setColorFunction(cogUrl, undefined);
    };
  }, [disturbances, onCameraChange, onError, onSelect]);

  return (
    <div ref={containerRef} className="disturbance-map" aria-label="2017 to 2018 spectral change map">
      <div className="disturbance-label" aria-label="2017 to 2018 spectral change">
        <span>2017 → 2018</span>
        <small>SPECTRAL CHANGE</small>
      </div>
      <div className="disturbance-background-label">2018 reference imagery</div>
      <section className="disturbance-legend" aria-label="2017 to 2018 spectral change legend">
        <strong>2017–2018 spectral change</strong>
        <div className="disturbance-legend-ramp" aria-hidden="true"><span /></div>
        <div className="disturbance-legend-values">
          <span>&lt; 0<small>NBR increase</small></span>
          <span>0<small>Little net change</small></span>
          <span>0.30<small>Detection threshold component</small></span>
          <span>0.60<small>Large NBR decrease</small></span>
          <span>≥ 1.0<small>Very large NBR decrease</small></span>
        </div>
        <p>dNBR = NBR2017 − NBR2018</p>
        <p>Detected disturbance also required 2017 NBR &gt; 0.30</p>
      </section>
      {!rasterLoaded && <div className="imagery-loading disturbance-loading" role="status">Loading spectral change…</div>}
    </div>
  );
}
