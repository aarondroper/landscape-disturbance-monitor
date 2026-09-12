import { useEffect, useState } from "react";
import { loadDisturbanceTimeseries, loadDisturbances, loadSummary } from "./data/loadData";
import type { DisturbanceCollection, DisturbanceProperties, DisturbanceSeriesLookup, SummaryData } from "./data/types";
import { AppHeader } from "./components/AppHeader";
import { DisturbanceDetails } from "./components/DisturbanceDetails";
import { LandscapeCompareMap } from "./map/LandscapeCompareMap";

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
      <AppHeader summary={summary} summaryError={summaryError} />
      {disturbances ? (
        <LandscapeCompareMap disturbances={disturbances} onSelect={setSelected} onError={setMapError} />
      ) : (
        <div className="map-placeholder" role="status">{dataError ?? "Loading disturbance landscape…"}</div>
      )}
      {disturbances && (
        <DisturbanceDetails
          disturbance={selected}
          series={selected ? timeseries?.[selected.disturbance_id] : undefined}
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
