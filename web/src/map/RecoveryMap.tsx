import * as maplibregl from "maplibre-gl";
import type { MapLayerMouseEvent, MapSourceDataEvent } from "maplibre-gl";
import { cogProtocol, setColorFunction } from "@geomatico/maplibre-cog-protocol";
import { useCallback, useEffect, useRef, useState } from "react";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { AFTER_IMAGERY_YEAR, calculateBounds, RECOVERY_YEARS, type RecoveryYear } from "../data/loadData";
import type { DisturbanceCollection, DisturbanceProperties } from "../data/types";
import { cameraSnapshotOf, MAP_FIT_PADDING, type CameraSnapshot } from "./camera";
import { recoveryColorFunction } from "./recoveryColor";
import {
  DISTURBANCE_FILL_LAYER_ID,
  DISTURBANCE_SOURCE_ID,
  disturbanceLayers,
  disturbanceSource,
  imagerySource,
  RECOVERY_BACKGROUND_SOURCE_ID,
  recoveryCogUrl,
  recoveryBackgroundLayer,
  recoveryLayer,
  recoveryLayerId,
  recoverySource,
  recoverySourceId,
  setDisturbanceLayersVisible,
} from "./mapLayers";
import { setDisturbanceFeatureState } from "./interactionState";
import { localMapStyle } from "./mapStyle";

maplibregl.addProtocol("cog", cogProtocol);
maplibregl.setWorkerUrl(workerUrl);

interface RecoveryMapProps {
  disturbances: DisturbanceCollection;
  selectedId?: string;
  selectedYear: RecoveryYear;
  initialCamera?: CameraSnapshot;
  onSelect: (disturbance?: DisturbanceProperties) => void;
  onError: (message: string) => void;
  onCameraChange: (camera: CameraSnapshot) => void;
  boundariesVisible: boolean;
}

interface ActiveRaster {
  year: RecoveryYear;
  sourceId: string;
  layerId: string;
}

export function RecoveryMap({ disturbances, selectedId, selectedYear, initialCamera, onSelect, onError, onCameraChange, boundariesVisible }: RecoveryMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const mapReadyRef = useRef(false);
  const selectedIdRef = useRef(selectedId);
  const selectedYearRef = useRef<RecoveryYear>(selectedYear);
  const activeRasterRef = useRef<ActiveRaster | undefined>(undefined);
  const hoveredIdRef = useRef<string | undefined>(undefined);
  const initialCameraRef = useRef(initialCamera);
  const boundariesVisibleRef = useRef(boundariesVisible);
  const [loadingYear, setLoadingYear] = useState<RecoveryYear>();

  useEffect(() => {
    const previousVisibility = boundariesVisibleRef.current;
    boundariesVisibleRef.current = boundariesVisible;
    const map = mapRef.current;
    if (!map || previousVisibility === boundariesVisible || !mapReadyRef.current) return;
    setDisturbanceLayersVisible(map, boundariesVisible);
    if (!boundariesVisible) {
      if (hoveredIdRef.current) setDisturbanceFeatureState(map, hoveredIdRef.current, "hover", false);
      hoveredIdRef.current = undefined;
      map.getCanvas().style.cursor = "";
    } else if (selectedIdRef.current) {
      setDisturbanceFeatureState(map, selectedIdRef.current, "selected", true);
    }
  }, [boundariesVisible]);

  const updateRecoveryRaster = useCallback((map: maplibregl.Map, year: RecoveryYear) => {
    const sourceId = recoverySourceId(year);
    const layerId = recoveryLayerId(year);
    const cogUrl = recoveryCogUrl(year);
    setColorFunction(cogUrl, recoveryColorFunction);
    const previous = activeRasterRef.current;
    const removeOtherRasters = () => {
      for (const candidateYear of RECOVERY_YEARS) {
        const candidateSourceId = recoverySourceId(candidateYear);
        const candidateLayerId = recoveryLayerId(candidateYear);
        if (candidateSourceId === sourceId) continue;
        if (map.getLayer(candidateLayerId)) map.removeLayer(candidateLayerId);
        if (map.getSource(candidateSourceId)) map.removeSource(candidateSourceId);
        setColorFunction(recoveryCogUrl(candidateYear), undefined);
      }
    };
    if (map.getSource(sourceId)) {
      activeRasterRef.current = { year, sourceId, layerId };
      removeOtherRasters();
      setLoadingYear(map.isSourceLoaded(sourceId) ? undefined : year);
      return;
    }

    map.addSource(sourceId, recoverySource(year));
    map.addLayer(recoveryLayer(year), DISTURBANCE_FILL_LAYER_ID);
    activeRasterRef.current = { year, sourceId, layerId };
    setLoadingYear(year);
    const finishLoading = () => {
      if (activeRasterRef.current?.sourceId !== sourceId || !map.isSourceLoaded(sourceId)) return;
      removeOtherRasters();
      setLoadingYear(undefined);
      map.off("sourcedata", handleSourceData);
      map.off("idle", finishLoading);
    };
    const handleSourceData = (event: MapSourceDataEvent) => {
      if (event.sourceId === sourceId && event.isSourceLoaded) finishLoading();
    };
    map.on("sourcedata", handleSourceData);
    map.on("idle", finishLoading);
    if (previous && previous.sourceId !== sourceId) {
      // Keep the previous raster visible until the new source has loaded.
      setLoadingYear(year);
    }
  }, []);

  useEffect(() => {
    selectedYearRef.current = selectedYear;
    const map = mapRef.current;
    if (map && mapReadyRef.current) updateRecoveryRaster(map, selectedYear);
  }, [selectedYear, updateRecoveryRaster]);

  useEffect(() => {
    const previousId = selectedIdRef.current;
    selectedIdRef.current = selectedId;
    const map = mapRef.current;
    if (!map) return;
    if (!boundariesVisibleRef.current) return;
    if (previousId && previousId !== selectedId) setDisturbanceFeatureState(map, previousId, "selected", false);
    if (boundariesVisibleRef.current && selectedId) setDisturbanceFeatureState(map, selectedId, "selected", true);
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
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");

    const resizeObserver = new ResizeObserver(() => map.resize());
    resizeObserver.observe(container);
    const featureId = (event: MapLayerMouseEvent): string | undefined => {
      const feature = event.features?.[0];
      if (!feature) return undefined;
      const id = feature.properties?.disturbance_id ?? feature.id;
      return id === undefined ? undefined : String(id);
    };
    const updateHover = (id: string | undefined) => {
      if (!boundariesVisibleRef.current) {
        map.getCanvas().style.cursor = "";
        return;
      }
      const previousId = hoveredIdRef.current;
      if (previousId && previousId !== id) setDisturbanceFeatureState(map, previousId, "hover", false);
      if (id) setDisturbanceFeatureState(map, id, "hover", true);
      hoveredIdRef.current = id;
      map.getCanvas().style.cursor = id ? "pointer" : "";
    };
    const selectFeature = (id: string | undefined) => {
      if (!boundariesVisibleRef.current) return;
      if (selectedIdRef.current && selectedIdRef.current !== id) setDisturbanceFeatureState(map, selectedIdRef.current, "selected", false);
      if (id) setDisturbanceFeatureState(map, id, "selected", true);
      selectedIdRef.current = id;
      onSelect(id ? disturbances.features.find((feature) => feature.properties.disturbance_id === id)?.properties : undefined);
    };
    const handleMapError = () => {
      onError("Unable to load recovery layer");
    };
    const reportCamera = () => onCameraChange(cameraSnapshotOf(map));
    map.on("error", handleMapError);
    map.on("moveend", reportCamera);

    const handleLoad = () => {
      if (disposed) return;
      map.addSource(RECOVERY_BACKGROUND_SOURCE_ID, imagerySource(AFTER_IMAGERY_YEAR));
      map.addLayer(recoveryBackgroundLayer());
      map.addSource(DISTURBANCE_SOURCE_ID, disturbanceSource(disturbances));
      for (const layer of disturbanceLayers()) map.addLayer(layer);
      setDisturbanceLayersVisible(map, boundariesVisibleRef.current);
      map.on("mouseenter", DISTURBANCE_FILL_LAYER_ID, (event: MapLayerMouseEvent) => updateHover(featureId(event)));
      map.on("mouseleave", DISTURBANCE_FILL_LAYER_ID, () => updateHover(undefined));
      map.on("click", DISTURBANCE_FILL_LAYER_ID, (event: MapLayerMouseEvent) => {
        const id = featureId(event);
        if (id) selectFeature(id);
      });
      map.on("click", (event) => {
        if (!boundariesVisibleRef.current) return;
        if (map.queryRenderedFeatures(event.point, { layers: [DISTURBANCE_FILL_LAYER_ID] }).length === 0) selectFeature(undefined);
      });
      if (!initialCameraRef.current) {
        const [west, south, east, north] = calculateBounds(disturbances);
        map.fitBounds([[west, south], [east, north]], { padding: MAP_FIT_PADDING, maxZoom: 11, duration: 0 });
      }
      markMapReady();
      updateRecoveryRaster(map, selectedYearRef.current);
    };
    const markMapReady = () => {
      if (disposed) return;
      if (!map.isStyleLoaded() || !map.getSource(DISTURBANCE_SOURCE_ID)) return;
      if (mapReadyRef.current) return;
      mapReadyRef.current = true;
      setDisturbanceLayersVisible(map, boundariesVisibleRef.current);
      if (boundariesVisibleRef.current && selectedIdRef.current) setDisturbanceFeatureState(map, selectedIdRef.current, "selected", true);
    };
    map.on("styledata", markMapReady);
    map.on("idle", markMapReady);
    map.once("load", handleLoad);

    return () => {
      disposed = true;
      resizeObserver.disconnect();
      map.off("load", handleLoad);
      map.off("styledata", markMapReady);
      map.off("idle", markMapReady);
      map.off("error", handleMapError);
      map.off("moveend", reportCamera);
      mapReadyRef.current = false;
      hoveredIdRef.current = undefined;
      mapRef.current = null;
      map.remove();
      activeRasterRef.current = undefined;
      for (const year of RECOVERY_YEARS) setColorFunction(recoveryCogUrl(year), undefined);
    };
  }, [disturbances, onCameraChange, onError, onSelect, updateRecoveryRaster]);

  return (
    <div ref={containerRef} className="recovery-map" aria-label="Annual spectral recovery map">
      <div className="recovery-label" aria-label={`${selectedYear} spectral recovery`}>
        <span>{selectedYear}</span>
        <small>SPECTRAL RECOVERY</small>
      </div>
      <div className="recovery-background-label">2018 reference imagery</div>
      {loadingYear && <div className="imagery-loading recovery-loading" role="status">Loading {loadingYear} recovery…</div>}
    </div>
  );
}
