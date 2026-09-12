import { useEffect, useState } from "react";
import { loadDisturbances, loadSummary } from "./data/loadData";
import type { DisturbanceCollection, DisturbanceProperties, SummaryData } from "./data/types";
import { AppHeader } from "./components/AppHeader";
import { DisturbanceDetails } from "./components/DisturbanceDetails";
import { LandscapeMap } from "./map/LandscapeMap";

export default function App() {
  const [disturbances, setDisturbances] = useState<DisturbanceCollection>();
  const [summary, setSummary] = useState<SummaryData>();
  const [summaryError, setSummaryError] = useState<string>();
  const [dataError, setDataError] = useState<string>();
  const [mapError, setMapError] = useState<string>();
  const [selected, setSelected] = useState<DisturbanceProperties>();

  useEffect(() => {
    void loadSummary().then(setSummary).catch((error: unknown) => {
      setSummaryError(error instanceof Error ? error.message : "Could not load project summary.");
    });
    void loadDisturbances().then(setDisturbances).catch((error: unknown) => {
      setDataError(error instanceof Error ? error.message : "Could not load disturbance geography.");
    });
  }, []);

  return (
    <main className="app-shell">
      <AppHeader summary={summary} summaryError={summaryError} />
      <div className="imagery-state" aria-label="Current imagery">
        <span className="state-year">2018</span>
        <span className="state-label">Post-disturbance</span>
      </div>
      {disturbances ? (
        <LandscapeMap disturbances={disturbances} onSelect={setSelected} onError={setMapError} />
      ) : (
        <div className="map-placeholder" role="status">{dataError ?? "Loading disturbance landscape…"}</div>
      )}
      {disturbances && <DisturbanceDetails disturbance={selected} />}
      {(summaryError || mapError) && (
        <div className="runtime-notice" role="status">{summaryError ?? mapError}</div>
      )}
    </main>
  );
}
