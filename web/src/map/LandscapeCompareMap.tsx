import "@geoql/maplibre-gl-compare/style.css";
import { Compare } from "@geoql/maplibre-gl-compare";
import * as maplibregl from "maplibre-gl";
import type { MapLayerMouseEvent } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { useEffect, useRef, useState } from "react";
import { cogProtocol } from "@geomatico/maplibre-cog-protocol";
import { AFTER_IMAGERY_YEAR, BEFORE_IMAGERY_YEAR, calculateBounds } from "../data/loadData";
import type { DisturbanceCollection, DisturbanceProperties } from "../data/types";
import { localMapStyle, MAP_OVERLAY_SURFACE_COLOR } from "./mapStyle";
import {
  comparisonLabels,
  DISTURBANCE_FILL_LAYER_ID,
  DISTURBANCE_SOURCE_ID,
  disturbanceLayers,
  disturbanceSource,
  imagerySource,
  imagerySourceId,
  INITIAL_DIVIDER_PERCENT,
  setDisturbanceLayersVisible,
} from "./mapLayers";
import { replaceMirroredFeatureState, setDisturbanceFeatureState, setMirroredFeatureState } from "./interactionState";
import { cleanupComparisonResources } from "./comparisonLifecycle";
import type { CameraSnapshot } from "./camera";
import { cameraSnapshotOf, MAP_FIT_PADDING } from "./camera";

maplibregl.addProtocol("cog", cogProtocol);
maplibregl.setWorkerUrl(workerUrl);

interface LandscapeCompareMapProps {
  disturbances: DisturbanceCollection;
  onSelect: (disturbance?: DisturbanceProperties) => void;
  onError: (message: string) => void;
  selectedId?: string;
  initialCamera?: CameraSnapshot;
  onCameraChange: (camera: CameraSnapshot) => void;
  boundariesVisible: boolean;
}

export function LandscapeCompareMap({ disturbances, onSelect, onError, selectedId, initialCamera, onCameraChange, boundariesVisible }: LandscapeCompareMapProps) {
  const comparisonRef = useRef<HTMLDivElement>(null);
  const beforeContainerRef = useRef<HTMLDivElement>(null);
  const afterContainerRef = useRef<HTMLDivElement>(null);
  const selectedIdRef = useRef<string | undefined>(selectedId);
  const initialCameraRef = useRef(initialCamera);
  const hoveredIdRef = useRef<string | undefined>(undefined);
  const compareRef = useRef<Compare | undefined>(undefined);
  const mapsRef = useRef<maplibregl.Map[]>([]);
  const boundariesVisibleRef = useRef(boundariesVisible);
  const [loadedYears, setLoadedYears] = useState<Set<number>>(new Set());

  useEffect(() => {
    const previousVisibility = boundariesVisibleRef.current;
    boundariesVisibleRef.current = boundariesVisible;
    if (previousVisibility === boundariesVisible) return;
    for (const map of mapsRef.current) setDisturbanceLayersVisible(map, boundariesVisible);
    if (!boundariesVisible) {
      if (hoveredIdRef.current) setMirroredFeatureState(mapsRef.current, hoveredIdRef.current, "hover", false);
      hoveredIdRef.current = undefined;
      for (const map of mapsRef.current) map.getCanvas().style.cursor = "";
    } else if (selectedIdRef.current) {
      setMirroredFeatureState(mapsRef.current, selectedIdRef.current, "selected", true);
    }
  }, [boundariesVisible]);

  useEffect(() => {
    const comparisonContainer = comparisonRef.current;
    const beforeContainer = beforeContainerRef.current;
    const afterContainer = afterContainerRef.current;
    if (!comparisonContainer || !beforeContainer || !afterContainer) return;

    const beforeMap = new maplibregl.Map({
      container: beforeContainer,
      style: localMapStyle,
      center: [15.5, 61.9],
      zoom: 8,
      pitch: 0,
      bearing: 0,
      attributionControl: false,
    });
    const afterMap = new maplibregl.Map({
      container: afterContainer,
      style: localMapStyle,
      center: [15.5, 61.9],
      zoom: 8,
      pitch: 0,
      bearing: 0,
      attributionControl: false,
    });
    const maps = [beforeMap, afterMap] as const;
    mapsRef.current = [...maps];
    afterMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    afterMap.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-right");

    const resizeObserver = new ResizeObserver(() => {
      beforeMap.resize();
      afterMap.resize();
    });
    resizeObserver.observe(comparisonContainer);

    const readyMaps = new Map<number, maplibregl.Map>();
    const mapListeners: Array<() => void> = [];
    mapListeners.push(() => resizeObserver.disconnect());

    const handleMapError = (year: number) => () => {
      onError(`Unable to load ${year} imagery`);
    };

    const updateHover = (id: string | undefined) => {
      if (!boundariesVisibleRef.current) {
        for (const map of maps) map.getCanvas().style.cursor = "";
        return;
      }
      const previousId = hoveredIdRef.current;
      if (previousId === id) return;
      if (previousId) setMirroredFeatureState(maps, previousId, "hover", false);
      if (id) setMirroredFeatureState(maps, id, "hover", true);
      hoveredIdRef.current = id;
      for (const map of maps) map.getCanvas().style.cursor = id ? "pointer" : "";
    };

    const selectFeature = (id: string | undefined) => {
      if (!boundariesVisibleRef.current) return;
      replaceMirroredFeatureState(maps, selectedIdRef.current, id, "selected");
      selectedIdRef.current = id;
      const selected = id ? disturbances.features.find((feature) => feature.properties.disturbance_id === id) : undefined;
      onSelect(selected?.properties);
    };

    const featureId = (event: MapLayerMouseEvent): string | undefined => {
      const feature = event.features?.[0];
      if (!feature) return undefined;
      const id = feature.properties?.disturbance_id ?? feature.id;
      return id === undefined ? undefined : String(id);
    };

    const addMapContent = (map: maplibregl.Map, year: number) => {
      const imageryId = imagerySourceId(year);
      map.addSource(imageryId, imagerySource(year));
      map.addLayer({
        id: `${imageryId}-layer`,
        source: imageryId,
        type: "raster",
        paint: { "raster-opacity": 1, "raster-fade-duration": 0 },
      });
      map.addSource(DISTURBANCE_SOURCE_ID, disturbanceSource(disturbances));
      for (const layer of disturbanceLayers()) map.addLayer(layer);
      setDisturbanceLayersVisible(map, boundariesVisibleRef.current);
      if (boundariesVisibleRef.current && selectedIdRef.current) setDisturbanceFeatureState(map, selectedIdRef.current, "selected", true);
      if (boundariesVisibleRef.current && hoveredIdRef.current) setDisturbanceFeatureState(map, hoveredIdRef.current, "hover", true);

      map.on("mouseenter", DISTURBANCE_FILL_LAYER_ID, (event: MapLayerMouseEvent) => {
        updateHover(featureId(event));
      });
      map.on("mouseleave", DISTURBANCE_FILL_LAYER_ID, () => updateHover(undefined));
      map.on("click", DISTURBANCE_FILL_LAYER_ID, (event: MapLayerMouseEvent) => {
        const id = featureId(event);
        if (id) selectFeature(id);
      });
      map.on("click", (event) => {
        if (!boundariesVisibleRef.current) return;
        if (map.queryRenderedFeatures(event.point, { layers: [DISTURBANCE_FILL_LAYER_ID] }).length === 0) {
          selectFeature(undefined);
        }
      });

      const markImageryLoaded = () => {
        if (map.isSourceLoaded(imageryId)) {
          setLoadedYears((previous) => {
            if (previous.has(year)) return previous;
            const next = new Set(previous);
            next.add(year);
            return next;
          });
        }
      };
      map.on("idle", markImageryLoaded);
      mapListeners.push(() => map.off("idle", markImageryLoaded));
    };

    const initializeCompare = () => {
      if (readyMaps.size !== 2 || compareRef.current) return;
      const bounds = calculateBounds(disturbances);
      if (!bounds) return;
      const [west, south, east, north] = bounds;
      if (initialCameraRef.current) {
        beforeMap.jumpTo(initialCameraRef.current);
        afterMap.jumpTo(initialCameraRef.current);
      } else {
        beforeMap.fitBounds([[west, south], [east, north]], {
          padding: MAP_FIT_PADDING,
          maxZoom: 11,
          duration: 0,
        });
        afterMap.jumpTo(cameraSnapshotOf(beforeMap));
      }

      const compare = new Compare(beforeMap, afterMap, comparisonContainer, {
        orientation: "vertical",
        mousemove: false,
        swiperIcon: "↔",
        theme: "light",
        lightColors: {
          swiperBackground: MAP_OVERLAY_SURFACE_COLOR,
          swiperBorder: "rgba(67, 63, 52, 0.42)",
          lineBackground: "rgba(250, 248, 242, 0.96)",
        },
        swiperStyle: {
          width: "24px",
          height: "24px",
          boxShadow: "0 2px 8px rgba(55, 49, 37, 0.2)",
          border: "1px solid rgba(67, 63, 52, 0.42)",
          backgroundColor: MAP_OVERLAY_SURFACE_COLOR,
        },
      });
      compare.setSlider((comparisonContainer.clientWidth * INITIAL_DIVIDER_PERCENT) / 100);
      compareRef.current = compare;

      const reportCamera = () => onCameraChange(cameraSnapshotOf(afterMap));
      afterMap.on("moveend", reportCamera);
      mapListeners.push(() => afterMap.off("moveend", reportCamera));

      const swiper = comparisonContainer.querySelector<HTMLElement>(".compare-swiper-vertical");
      if (!swiper) return;
      const updateSliderAccessibility = (position: number) => {
        const width = comparisonContainer.clientWidth || 1;
        const value = Math.round((position / width) * 100);
        swiper.setAttribute("aria-valuenow", String(value));
        swiper.setAttribute("aria-valuetext", `${value}% comparison position`);
      };
      swiper.tabIndex = 0;
      swiper.setAttribute("role", "slider");
      swiper.setAttribute("aria-label", "Compare 2017 and 2018 imagery");
      swiper.setAttribute("aria-valuemin", "0");
      swiper.setAttribute("aria-valuemax", "100");
      updateSliderAccessibility(compare.currentPosition);
      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        const direction = event.key === "ArrowRight" ? 1 : -1;
        const step = Math.max(8, comparisonContainer.clientWidth * 0.05);
        const nextPosition = compare.currentPosition + direction * step;
        compare.setSlider(nextPosition);
        updateSliderAccessibility(compare.currentPosition);
      };
      swiper.addEventListener("keydown", handleKeyDown);
      const handleSlideEnd = ({ currentPosition }: { currentPosition: number }) => updateSliderAccessibility(currentPosition);
      compare.on("slideend", handleSlideEnd);
      mapListeners.push(() => {
        swiper.removeEventListener("keydown", handleKeyDown);
        compare.off("slideend", handleSlideEnd);
      });
    };

    const initializeMap = (map: maplibregl.Map, year: number) => {
      const handleErrorForMap = handleMapError(year);
      map.on("error", handleErrorForMap);
      mapListeners.push(() => map.off("error", handleErrorForMap));
      const handleLoad = () => {
        addMapContent(map, year);
        readyMaps.set(year, map);
        initializeCompare();
      };
      map.once("load", handleLoad);
    };

    initializeMap(beforeMap, BEFORE_IMAGERY_YEAR);
    initializeMap(afterMap, AFTER_IMAGERY_YEAR);

    return () => {
      cleanupComparisonResources(compareRef.current, maps, mapListeners);
      compareRef.current = undefined;
      document.documentElement.style.removeProperty("--compare-swiper-bg");
      document.documentElement.style.removeProperty("--compare-swiper-border");
      document.documentElement.style.removeProperty("--compare-line-bg");
      mapsRef.current = [];
    };
  }, [disturbances, onError, onSelect, onCameraChange]);

  useEffect(() => {
    const previousId = selectedIdRef.current;
    selectedIdRef.current = selectedId;
    if (!boundariesVisibleRef.current) return;
    if (previousId && previousId !== selectedId) {
      setMirroredFeatureState(mapsRef.current, previousId, "selected", false);
    }
    if (selectedId) setMirroredFeatureState(mapsRef.current, selectedId, "selected", true);
  }, [selectedId]);

  const isLoading = loadedYears.size < 2;
  return (
    <div ref={comparisonRef} className="comparison-map" aria-label="2017 and 2018 disturbance imagery comparison">
      <div ref={beforeContainerRef} className="comparison-map-pane comparison-map-pane--before" aria-label="2017 pre-disturbance map" />
      <div ref={afterContainerRef} className="comparison-map-pane comparison-map-pane--after" aria-label="2018 post-disturbance map" />
      <div className="imagery-label imagery-label--before" aria-label={`${comparisonLabels.before.year} ${comparisonLabels.before.descriptor}`}>
        <span>{comparisonLabels.before.year}</span>
        <small>{comparisonLabels.before.descriptor}</small>
      </div>
      <div className="imagery-label imagery-label--after" aria-label={`${comparisonLabels.after.year} ${comparisonLabels.after.descriptor}`}>
        <span>{comparisonLabels.after.year}</span>
        <small>{comparisonLabels.after.descriptor}</small>
      </div>
      {isLoading && <div className="imagery-loading" role="status">Loading imagery…</div>}
      <div className="comparison-hint">Drag to compare</div>
    </div>
  );
}
