import { useCallback, useEffect, useState } from "react";
import { loadDisturbanceTimeseries, loadDisturbances, loadSummary } from "./data/loadData";
import type { DisturbanceCollection, DisturbanceProperties, DisturbanceSeriesLookup, SummaryData } from "./data/types";
import { AppHeader } from "./components/AppHeader";
import { DisturbanceDetails } from "./components/DisturbanceDetails";
import { LandscapeCompareMap } from "./map/LandscapeCompareMap";
import { RecoveryMap } from "./map/RecoveryMap";
import type { CameraSnapshot } from "./map/camera";
import { DEFAULT_MAP_MODE, DEFAULT_RECOVERY_YEAR } from "./map/viewMode";
import type { MapViewMode } from "./map/viewMode";
import type { RecoveryYear } from "./data/loadData";

export default function App() {
  const [disturbances, setDisturbances] = useState<DisturbanceCollection>();
  const [summary, setSummary] = useState<SummaryData>();
  const [summaryError, setSummaryError] = useState<string>();
  const [dataError, setDataError] = useState<string>();
  const [timeseries, setTimeseries] = useState<DisturbanceSeriesLookup>();
  const [timeseriesError, setTimeseriesError] = useState<string>();
  const [timeseriesLoading, setTimeseriesLoading] = useState(true);
  const [mapError, setMapError] = useState<string>();
  const [selected, setSelected] = useState<DisturbanceProperties>();
  const [mapMode, setMapMode] = useState<MapViewMode>(DEFAULT_MAP_MODE);
  const [recoveryYear, setRecoveryYear] = useState<RecoveryYear>(DEFAULT_RECOVERY_YEAR);
  const [camera, setCamera] = useState<CameraSnapshot>();

  const handleSelect = useCallback((disturbance?: DisturbanceProperties) => setSelected(disturbance), []);
  const handleMapError = useCallback((message: string) => setMapError(message), []);
  const handleCameraChange = useCallback((nextCamera: CameraSnapshot) => setCamera(nextCamera), []);

  useEffect(() => {
    void loadSummary().then(setSummary).catch((error: unknown) => {
      setSummaryError(error instanceof Error ? error.message : "Could not load project summary.");
    });
    void loadDisturbances().then(setDisturbances).catch((error: unknown) => {
      setDataError(error instanceof Error ? error.message : "Could not load disturbance geography.");
    });
    void loadDisturbanceTimeseries()
      .then(setTimeseries)
      .catch((error: unknown) => {
        setTimeseriesError(error instanceof Error ? error.message : "Could not load disturbance time series.");
      })
      .finally(() => setTimeseriesLoading(false));
  }, []);

  return (
    <main className="app-shell">
      <AppHeader summary={summary} summaryError={summaryError} mode={mapMode} onModeChange={setMapMode} />
      {disturbances ? (
        mapMode === "compare" ? (
          <LandscapeCompareMap
            disturbances={disturbances}
            selectedId={selected?.disturbance_id}
            initialCamera={camera}
            onSelect={handleSelect}
            onError={handleMapError}
            onCameraChange={handleCameraChange}
          />
        ) : (
          <RecoveryMap
            disturbances={disturbances}
            selectedId={selected?.disturbance_id}
            selectedSeries={selected ? timeseries?.[selected.disturbance_id] : undefined}
            selectedYear={recoveryYear}
            initialCamera={camera}
            onYearChange={setRecoveryYear}
            onSelect={handleSelect}
            onError={handleMapError}
            onCameraChange={handleCameraChange}
          />
        )
      ) : (
        <div className="map-placeholder" role="status">{dataError ?? "Loading disturbance landscape…"}</div>
      )}
      {disturbances && (
        <DisturbanceDetails
          disturbance={selected}
          series={selected ? timeseries?.[selected.disturbance_id] : undefined}
          mapMode={mapMode}
          mappedYear={mapMode === "recovery" ? recoveryYear : undefined}
          timeseriesStatus={timeseriesLoading ? "loading" : timeseriesError ? "error" : "ready"}
          timeseriesError={timeseriesError}
        />
      )}
      {(summaryError || mapError) && (
        <div className="runtime-notice" role="status">{summaryError ?? mapError}</div>
      )}
    </main>
  );
}
