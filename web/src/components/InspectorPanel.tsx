import { coverageDisplay, coverageShortLabel, observationForYear, RECOVERY_YEARS, type RecoveryYear } from "../data/loadData";
import type { DisturbanceProperties, DisturbanceSeries } from "../data/types";
import type { MapViewMode } from "../map/viewMode";
import { DisturbanceDetails } from "./DisturbanceDetails";

interface InspectorPanelProps {
  disturbance?: DisturbanceProperties;
  series?: DisturbanceSeries;
  mapMode: MapViewMode;
  mappedYear?: number;
  recoveryYear: RecoveryYear;
  onRecoveryYearChange: (year: RecoveryYear) => void;
  timeseriesStatus: "loading" | "ready" | "error";
  timeseriesError?: string;
}

interface RecoveryInspectorProps {
  series?: DisturbanceSeries;
  selectedYear: RecoveryYear;
  onYearChange: (year: RecoveryYear) => void;
}

function RecoveryInspector({ series, selectedYear, onYearChange }: RecoveryInspectorProps) {
  const selectedObservation = observationForYear(series, selectedYear);
  const coverage = selectedObservation
    ? coverageDisplay(selectedObservation.coverage_status, selectedObservation.reporting_recommended)
    : undefined;

  return (
    <section className="inspector-section recovery-inspector" aria-label="Recovery controls and legend">
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
  );
}

export function InspectorPanel({ disturbance, series, mapMode, mappedYear, recoveryYear, onRecoveryYearChange, timeseriesStatus, timeseriesError }: InspectorPanelProps) {
  const isRecovery = mapMode === "recovery";
  return (
    <aside className="inspector-panel" aria-label="Disturbance inspector">
      {isRecovery && (
        <RecoveryInspector
          series={series}
          selectedYear={recoveryYear}
          onYearChange={onRecoveryYearChange}
        />
      )}
      <DisturbanceDetails
        disturbance={disturbance}
        series={series}
        mapMode={mapMode}
        mappedYear={mappedYear}
        showCoverage={!isRecovery}
        timeseriesStatus={timeseriesStatus}
        timeseriesError={timeseriesError}
      />
    </aside>
  );
}
