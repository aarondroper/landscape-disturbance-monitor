import { useState, type ReactElement } from "react";
import { coverageLabel } from "../data/loadData";
import { buildTrustedSegments, isMappedTimelineYear, recoveryDomain } from "../data/timeline";
import type { AnnualObservation, DisturbanceSeries } from "../data/types";

interface RecoveryTimelineProps {
  series: DisturbanceSeries;
  mappedYear?: number;
}

const WIDTH = 360;
const HEIGHT = 320;
const PLOT_LEFT = 35;
const PLOT_RIGHT = 8;
const PLOT_WIDTH = WIDTH - PLOT_LEFT - PLOT_RIGHT;
const NBR_TOP = 25;
const NBR_BOTTOM = 91;
const RECOVERY_TOP = 132;
const RECOVERY_BOTTOM = 240;
const YEARS = Array.from({ length: 10 }, (_, index) => 2017 + index);

function xFor(index: number): number {
  return PLOT_LEFT + (index / (YEARS.length - 1)) * PLOT_WIDTH;
}

function yFor(value: number, domain: [number, number], top: number, bottom: number): number {
  return bottom - ((value - domain[0]) / (domain[1] - domain[0])) * (bottom - top);
}

function linePoints(
  observations: readonly AnnualObservation[],
  value: (observation: AnnualObservation) => number | null,
  domain: [number, number],
  top: number,
  bottom: number,
): string {
  return observations
    .map((observation) => {
      const index = YEARS.indexOf(observation.year);
      const metric = value(observation);
      return metric === null || index < 0 ? undefined : `${xFor(index)},${yFor(metric, domain, top, bottom)}`;
    })
    .filter((point): point is string => point !== undefined)
    .join(" ");
}

function formatValue(value: number | null, digits = 3): string {
  return value === null ? "Not available" : value.toFixed(digits);
}

function formatFraction(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function pointShape(
  observation: AnnualObservation,
  metric: "nbr" | "recovery",
  index: number,
  domain: [number, number],
  mappedYear?: number,
): ReactElement {
  const x = xFor(index);
  const value = metric === "nbr" ? observation.nbr_median : observation.recovery_median;
  if (value === null) return <g key={`${metric}-${observation.year}`} />;
  const y = metric === "nbr"
    ? yFor(value, [-1, 1], NBR_TOP, NBR_BOTTOM)
    : yFor(value, domain, RECOVERY_TOP, RECOVERY_BOTTOM);
  const poor = observation.coverage_status === "POOR";
  const usable = observation.coverage_status === "USABLE_WITH_COVERAGE_FLAG";
  const mapped = isMappedTimelineYear(observation.year, mappedYear);
  const className = `timeline-point timeline-point--${metric} timeline-point--${observation.coverage_status.toLowerCase()}${mapped ? " timeline-point--mapped" : ""}`;

  if (poor) {
    return <rect className={className} x={x - 3.3} y={y - 3.3} width="6.6" height="6.6" fill="var(--panel-bg)" stroke="currentColor" />;
  }
  if (usable) {
    return <path className={className} d={`M ${x} ${y - 4} L ${x + 4} ${y} L ${x} ${y + 4} L ${x - 4} ${y} Z`} />;
  }
  return <circle className={className} cx={x} cy={y} r="3.4" />;
}

function observationLabel(observation: AnnualObservation): string {
  const recovery = observation.recovery_median === null ? "not available" : `${observation.recovery_median.toFixed(3)} times`;
  return `${observation.year}: NBR ${formatValue(observation.nbr_median)}, spectral recovery ${recovery}, ${coverageLabel(observation.coverage_status)}`;
}

export function RecoveryTimeline({ series, mappedYear }: RecoveryTimelineProps) {
  const [focusedYear, setFocusedYear] = useState<number>();
  const recoveryYDomain = recoveryDomain(series);
  const recoverySegments = buildTrustedSegments(series.series, "recovery_median");
  const nbrSegments = buildTrustedSegments(series.series, "nbr_median");
  const focusedObservation = series.series.find((observation) => observation.year === focusedYear);
  const zeroY = yFor(0, recoveryYDomain, RECOVERY_TOP, RECOVERY_BOTTOM);
  const oneY = yFor(1, recoveryYDomain, RECOVERY_TOP, RECOVERY_BOTTOM);

  return (
    <section className="timeline" aria-labelledby="timeline-title">
      <div className="timeline-heading">
        <div>
          <h3 id="timeline-title">Spectral trajectory</h3>
          <p>Annual NBR and recovery relative to the 2017 NBR baseline.</p>
        </div>
        <span className="timeline-years">2017–2026</span>
      </div>
      <div className="timeline-chart-wrap">
        <svg className="timeline-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img">
          <title>Annual NBR and spectral recovery trajectory</title>
          <desc>
            Ten discrete annual observations from 2017 through 2026. Primary lines break at poor coverage or missing observations; poor observations remain visible as muted points.
          </desc>
          <g className="timeline-grid" aria-hidden="true">
            {[-1, 0, 1].map((value) => {
              const y = yFor(value, [-1, 1], NBR_TOP, NBR_BOTTOM);
              return <line key={`nbr-grid-${value}`} x1={PLOT_LEFT} x2={WIDTH - PLOT_RIGHT} y1={y} y2={y} />;
            })}
            {[zeroY, oneY].map((y, index) => <line key={`recovery-reference-${index}`} x1={PLOT_LEFT} x2={WIDTH - PLOT_RIGHT} y1={y} y2={y} />)}
          </g>
          <g className="timeline-axis-labels" aria-hidden="true">
            <text x="0" y={NBR_TOP + 4}>NBR</text>
            <text x={PLOT_LEFT} y={NBR_TOP + 4} textAnchor="end">1</text>
            <text x={PLOT_LEFT} y={yFor(0, [-1, 1], NBR_TOP, NBR_BOTTOM) + 4} textAnchor="end">0</text>
            <text x={PLOT_LEFT} y={NBR_BOTTOM + 4} textAnchor="end">−1</text>
            <text x="0" y={RECOVERY_TOP + 4}>Recovery</text>
            <text x={PLOT_LEFT} y={zeroY + 4} textAnchor="end">0</text>
            <text x={PLOT_LEFT} y={oneY + 4} textAnchor="end">1</text>
            <text className="timeline-reference-label" x={WIDTH - PLOT_RIGHT} y={oneY - 5} textAnchor="end">2017 baseline</text>
            <text className="timeline-reference-label" x={WIDTH - PLOT_RIGHT} y={zeroY + 13} textAnchor="end">Post-disturbance baseline</text>
          </g>
          <g className="timeline-lines" aria-hidden="true">
            {nbrSegments.map((segment, index) => (
              <polyline className="timeline-line timeline-line--nbr" key={`nbr-line-${index}`} points={linePoints(segment, (observation) => observation.nbr_median, [-1, 1], NBR_TOP, NBR_BOTTOM)} />
            ))}
            {recoverySegments.map((segment, index) => (
              <polyline className="timeline-line timeline-line--recovery" key={`recovery-line-${index}`} points={linePoints(segment, (observation) => observation.recovery_median, recoveryYDomain, RECOVERY_TOP, RECOVERY_BOTTOM)} />
            ))}
            {mappedYear !== undefined && YEARS.includes(mappedYear) && (
              <line className="timeline-active-year" x1={xFor(YEARS.indexOf(mappedYear))} x2={xFor(YEARS.indexOf(mappedYear))} y1={NBR_TOP - 5} y2={RECOVERY_BOTTOM + 5} />
            )}
          </g>
          <g className="timeline-ranges" aria-hidden="true">
            {series.series.map((observation, index) => {
              if (observation.recovery_p10 === null || observation.recovery_p90 === null) return null;
              const low = Math.min(observation.recovery_p10, observation.recovery_p90);
              const high = Math.max(observation.recovery_p10, observation.recovery_p90);
              return (
                <line
                  key={`range-${observation.year}`}
                  className={`timeline-range timeline-range--${observation.coverage_status.toLowerCase()}`}
                  x1={xFor(index)}
                  x2={xFor(index)}
                  y1={yFor(low, recoveryYDomain, RECOVERY_TOP, RECOVERY_BOTTOM)}
                  y2={yFor(high, recoveryYDomain, RECOVERY_TOP, RECOVERY_BOTTOM)}
                />
              );
            })}
          </g>
          <g className="timeline-points" aria-hidden="true">
            {series.series.map((observation, index) => pointShape(observation, "nbr", index, recoveryYDomain, mappedYear))}
            {series.series.map((observation, index) => pointShape(observation, "recovery", index, recoveryYDomain, mappedYear))}
          </g>
          <g className="timeline-focus-targets">
            {series.series.map((observation, index) => (
              <rect
                key={`focus-${observation.year}`}
                className="timeline-focus-target"
                x={xFor(index) - 11}
                y={NBR_TOP - 10}
                width="22"
                height={RECOVERY_BOTTOM - NBR_TOP + 20}
                tabIndex={0}
                role="button"
                aria-label={observationLabel(observation)}
                onMouseEnter={() => setFocusedYear(observation.year)}
                onMouseLeave={() => setFocusedYear(undefined)}
                onFocus={() => setFocusedYear(observation.year)}
                onBlur={() => setFocusedYear(undefined)}
              />
            ))}
          </g>
          <g className="timeline-years-axis" aria-hidden="true">
            {YEARS.map((year, index) => (
              <text key={year} x={xFor(index)} y="273" textAnchor="middle" className={index % 2 === 0 || index === YEARS.length - 1 ? "" : "timeline-year-hidden"}>
                {year}
              </text>
            ))}
          </g>
        </svg>
        {focusedObservation && (
          <div className="timeline-tooltip" role="status" aria-live="polite">
            <strong>{focusedObservation.year}</strong>
            <span>NBR median: {formatValue(focusedObservation.nbr_median)}</span>
            <span>Spectral recovery: {focusedObservation.recovery_median === null ? "Not available" : `${focusedObservation.recovery_median.toFixed(3)}×`}</span>
            <span>P10–P90 pixel range: {focusedObservation.recovery_p10 === null || focusedObservation.recovery_p90 === null ? "Not available" : `${focusedObservation.recovery_p10.toFixed(3)}–${focusedObservation.recovery_p90.toFixed(3)}`}</span>
            <span>NBR valid imagery: {formatFraction(focusedObservation.nbr_valid_fraction)}</span>
            <span>{coverageLabel(focusedObservation.coverage_status)}{focusedObservation.coverage_status === "POOR" ? " · Limited valid imagery" : ""}</span>
          </div>
        )}
      </div>
      <div className="timeline-legend" aria-label="Trajectory legend">
        <span><i className="legend-swatch legend-swatch--nbr" /> NBR median</span>
        <span><i className="legend-swatch legend-swatch--recovery" /> Recovery median</span>
        <span><i className="legend-swatch legend-swatch--range" /> P10–P90 pixel range</span>
        <span><i className="legend-swatch legend-swatch--poor" /> Poor coverage retained, line breaks</span>
      </div>
      <p className="timeline-note">Recovery is unbounded; 1.0 marks the 2017 spectral baseline, not an ecological condition. No interpolation or smoothing.</p>
    </section>
  );
}
