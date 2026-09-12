import * as maplibregl from "maplibre-gl";
import type { MapLayerMouseEvent, MapSourceDataEvent } from "maplibre-gl";
import { cogProtocol, setColorFunction } from "@geomatico/maplibre-cog-protocol";
import { useCallback, useEffect, useRef, useState } from "react";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { AFTER_IMAGERY_YEAR, calculateBounds, coverageDisplay, coverageShortLabel, observationForYear, RECOVERY_YEARS, type RecoveryYear } from "../data/loadData";
import type { DisturbanceCollection, DisturbanceProperties, DisturbanceSeries } from "../data/types";
import { cameraSnapshotOf, type CameraSnapshot } from "./camera";
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
} from "./mapLayers";
import { localMapStyle } from "./mapStyle";

maplibregl.addProtocol("cog", cogProtocol);
maplibregl.setWorkerUrl(workerUrl);

interface RecoveryMapProps {
  disturbances: DisturbanceCollection;
  selectedId?: string;
  selectedSeries?: DisturbanceSeries;
  selectedYear: RecoveryYear;
  initialCamera?: CameraSnapshot;
  onYearChange: (year: RecoveryYear) => void;
  onSelect: (disturbance?: DisturbanceProperties) => void;
  onError: (message: string) => void;
  onCameraChange: (camera: CameraSnapshot) => void;
}

interface ActiveRaster {
  year: RecoveryYear;
  sourceId: string;
  layerId: string;
}

export function RecoveryMap({ disturbances, selectedId, selectedSeries, selectedYear, initialCamera, onYearChange, onSelect, onError, onCameraChange }: RecoveryMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const mapReadyRef = useRef(false);
  const selectedIdRef = useRef(selectedId);
  const selectedYearRef = useRef<RecoveryYear>(selectedYear);
  const activeRasterRef = useRef<ActiveRaster | undefined>(undefined);
  const hoveredIdRef = useRef<string | undefined>(undefined);
  const initialCameraRef = useRef(initialCamera);
  const [loadingYear, setLoadingYear] = useState<RecoveryYear>();

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
    if (previousId && previousId !== selectedId) map.setFeatureState({ source: DISTURBANCE_SOURCE_ID, id: previousId }, { selected: false });
    if (selectedId) map.setFeatureState({ source: DISTURBANCE_SOURCE_ID, id: selectedId }, { selected: true });
  }, [selectedId]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
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
    const featureId = (event: MapLayerMouseEvent): string | undefined => {
      const feature = event.features?.[0];
      if (!feature) return undefined;
      const id = feature.properties?.disturbance_id ?? feature.id;
      return id === undefined ? undefined : String(id);
    };
    const updateHover = (id: string | undefined) => {
      const previousId = hoveredIdRef.current;
      if (previousId && previousId !== id) map.setFeatureState({ source: DISTURBANCE_SOURCE_ID, id: previousId }, { hover: false });
      if (id) map.setFeatureState({ source: DISTURBANCE_SOURCE_ID, id }, { hover: true });
      hoveredIdRef.current = id;
      map.getCanvas().style.cursor = id ? "pointer" : "";
    };
    const selectFeature = (id: string | undefined) => {
      if (selectedIdRef.current && selectedIdRef.current !== id) map.setFeatureState({ source: DISTURBANCE_SOURCE_ID, id: selectedIdRef.current }, { selected: false });
      if (id) map.setFeatureState({ source: DISTURBANCE_SOURCE_ID, id }, { selected: true });
      selectedIdRef.current = id;
      onSelect(id ? disturbances.features.find((feature) => feature.properties.disturbance_id === id)?.properties : undefined);
    };
    const handleMapError = () => {
      onError("Unable to load recovery layer");
    };
    const reportCamera = () => onCameraChange(cameraSnapshotOf(map));
    map.on("error", handleMapError);
    map.on("moveend", reportCamera);

    map.once("load", () => {
      map.addSource(RECOVERY_BACKGROUND_SOURCE_ID, imagerySource(AFTER_IMAGERY_YEAR));
      map.addLayer(recoveryBackgroundLayer());
      map.addSource(DISTURBANCE_SOURCE_ID, disturbanceSource(disturbances));
      for (const layer of disturbanceLayers()) map.addLayer(layer);
      if (selectedIdRef.current) map.setFeatureState({ source: DISTURBANCE_SOURCE_ID, id: selectedIdRef.current }, { selected: true });
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
        map.fitBounds([[west, south], [east, north]], { padding: { top: 96, right: 360, bottom: 72, left: 32 }, maxZoom: 11, duration: 0 });
      }
      mapReadyRef.current = true;
      updateRecoveryRaster(map, selectedYearRef.current);
    });

    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
      mapReadyRef.current = false;
      activeRasterRef.current = undefined;
      for (const year of RECOVERY_YEARS) setColorFunction(recoveryCogUrl(year), undefined);
    };
  }, [disturbances, onCameraChange, onError, onSelect, updateRecoveryRaster]);

  const selectedObservation = observationForYear(selectedSeries, selectedYear);
  const coverage = selectedObservation ? coverageDisplay(selectedObservation.coverage_status, selectedObservation.reporting_recommended) : undefined;
  return (
    <div ref={containerRef} className="recovery-map" aria-label="Annual spectral recovery map">
      <div className="recovery-label" aria-label={`${selectedYear} spectral recovery`}>
        <span>{selectedYear}</span>
        <small>SPECTRAL RECOVERY</small>
      </div>
      <div className="recovery-background-label">2018 reference imagery</div>
      <section className="recovery-controls" aria-label="Recovery map controls">
        <label className="recovery-year-control">
          <span className="panel-kicker">Recovery year</span>
          <strong>{selectedYear}</strong>
          <input
            type="range"
            min={RECOVERY_YEARS[0]}
            max={RECOVERY_YEARS[RECOVERY_YEARS.length - 1]}
            step="1"
            value={selectedYear}
            aria-label="Annual recovery map year"
            onChange={(event) => onYearChange(Number(event.target.value) as RecoveryYear)}
          />
          <span className="recovery-year-range"><span>2017</span><span>2026</span></span>
        </label>
        <div className="recovery-legend" aria-label="Spectral recovery legend">
          <strong>Spectral recovery</strong>
          <span className="recovery-legend-note">Relative to 2017 NBR baseline</span>
          <div className="recovery-legend-ramp" aria-hidden="true" />
          <div className="recovery-legend-values"><span>≤ 0<br /><small>Below 2018 state</small></span><span>0.5<br /><small>Partway toward baseline</small></span><span>1.0<br /><small>2017 NBR baseline</small></span><span>≥ 1.5<br /><small>Above baseline</small></span></div>
          <p className="recovery-legend-boundary">Values below 0 and above 1 remain visible.</p>
        </div>
        <div className="recovery-coverage" aria-live="polite">
          {coverage ? <><span>Selected area coverage: <strong>{coverageShortLabel(selectedObservation!.coverage_status)}</strong></span>{coverage.warning && <small>Limited valid imagery</small>}</> : <span>Select a disturbance for area coverage</span>}
        </div>
      </section>
      {loadingYear && <div className="imagery-loading recovery-loading" role="status">Loading {loadingYear} recovery…</div>}
    </div>
  );
}
