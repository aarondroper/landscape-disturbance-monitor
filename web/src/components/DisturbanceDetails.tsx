import { coverageDisplay, formatSpectralRecovery, observationForYear } from "../data/loadData";
import type { DisturbanceProperties, DisturbanceSeries } from "../data/types";
import type { MapViewMode } from "../map/viewMode";
import { RecoveryTimeline } from "./RecoveryTimeline";

interface DisturbanceDetailsProps {
  disturbance?: DisturbanceProperties;
  series?: DisturbanceSeries;
  mapMode: MapViewMode;
  mappedYear?: number;
  timeseriesStatus: "loading" | "ready" | "error";
  timeseriesError?: string;
}

function value(value: number, digits = 2): string {
  return value.toFixed(digits);
}

export function DisturbanceDetails({ disturbance, series, mapMode, mappedYear, timeseriesStatus, timeseriesError }: DisturbanceDetailsProps) {
  if (!disturbance) {
    return (
      <aside className="details-panel details-panel--quiet" aria-label="Disturbance details">
        <span className="panel-kicker">Disturbance geography</span>
        <h2>Select a disturbance area</h2>
        <p>Hover an outlined area, then click to inspect its browser-ready measurements.</p>
      </aside>
    );
  }

  const coverageYear = mapMode === "recovery" && mappedYear ? mappedYear : 2026;
  const mappedObservation = observationForYear(series, coverageYear);
  const coverage = coverageDisplay(
    mappedObservation?.coverage_status ?? disturbance.recovery_2026_coverage_status,
    mappedObservation?.reporting_recommended ?? disturbance.recovery_2026_reporting_recommended,
  );
  const coverageStatus = mappedObservation?.coverage_status ?? disturbance.recovery_2026_coverage_status;
  return (
    <aside className={`details-panel${mapMode === "recovery" ? " details-panel--recovery" : ""}`} aria-label={`Details for ${disturbance.disturbance_id}`}>
      <div className="panel-heading">
        <span className="panel-kicker">Selected disturbance</span>
        <span className="feature-id">{disturbance.disturbance_id}</span>
      </div>
      <dl className="detail-list">
        <div><dt>Area</dt><dd>{value(disturbance.area_ha)} ha</dd></div>
        <div><dt>2017 NBR</dt><dd>{value(disturbance.nbr_2017_median, 4)}</dd></div>
        <div><dt>2018 NBR</dt><dd>{value(disturbance.nbr_2018_median, 4)}</dd></div>
        <div><dt>2017–2018 dNBR</dt><dd>{value(disturbance.dnbr_median, 4)}</dd></div>
        <div><dt>2026 spectral recovery</dt><dd>{formatSpectralRecovery(disturbance.recovery_2026_median)}</dd></div>
      </dl>
      <div className={`coverage coverage--${coverageStatus.toLowerCase()}`}>
        <span className="coverage-label">{coverageYear} data coverage</span>
        <strong>{coverage.label}</strong>
      </div>
      <p className="qualifier">Spectral recovery relative to the 2017 NBR baseline.</p>
      {coverage.warning && (
        <p className="coverage-warning" role="status">Limited valid imagery for this year.</p>
      )}
      <div className="timeline-section">
        {timeseriesStatus === "loading" && <p className="timeline-message" role="status">Loading annual trajectory…</p>}
        {timeseriesStatus === "error" && <p className="timeline-message" role="status">{timeseriesError ?? "Annual trajectory could not be loaded."}</p>}
        {timeseriesStatus === "ready" && series && <RecoveryTimeline series={series} mappedYear={mappedYear} />}
        {timeseriesStatus === "ready" && !series && (
          <p className="timeline-message" role="status">No annual trajectory is available for this selection.</p>
        )}
      </div>
    </aside>
  );
}
