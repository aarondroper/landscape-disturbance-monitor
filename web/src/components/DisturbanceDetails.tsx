import { coverageDisplay, formatSpectralRecovery } from "../data/loadData";
import type { DisturbanceProperties } from "../data/types";

interface DisturbanceDetailsProps {
  disturbance?: DisturbanceProperties;
}

function value(value: number, digits = 2): string {
  return value.toFixed(digits);
}

export function DisturbanceDetails({ disturbance }: DisturbanceDetailsProps) {
  if (!disturbance) {
    return (
      <aside className="details-panel details-panel--quiet" aria-label="Disturbance details">
        <span className="panel-kicker">Disturbance geography</span>
        <h2>Select a disturbance area</h2>
        <p>Hover an outlined area, then click to inspect its browser-ready measurements.</p>
      </aside>
    );
  }

  const coverage = coverageDisplay(
    disturbance.recovery_2026_coverage_status,
    disturbance.recovery_2026_reporting_recommended,
  );
  return (
    <aside className="details-panel" aria-label={`Details for ${disturbance.disturbance_id}`}>
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
      <div className={`coverage coverage--${disturbance.recovery_2026_coverage_status.toLowerCase()}`}>
        <span className="coverage-label">2026 data coverage</span>
        <strong>{coverage.label}</strong>
      </div>
      <p className="qualifier">Spectral recovery relative to the 2017 NBR baseline.</p>
      {coverage.warning && (
        <p className="coverage-warning" role="status">Limited valid imagery for this year.</p>
      )}
    </aside>
  );
}
