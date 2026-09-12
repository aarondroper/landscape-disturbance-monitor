import type { AnnualObservation, DisturbanceSeries } from "./types";

export type TimelineMetric = "nbr_median" | "recovery_median";

export function buildTrustedSegments(
  observations: readonly AnnualObservation[],
  metric: TimelineMetric,
): AnnualObservation[][] {
  const segments: AnnualObservation[][] = [];
  let current: AnnualObservation[] = [];

  for (const observation of observations) {
    const value = observation[metric];
    const trusted = observation.coverage_status !== "POOR" && observation.reporting_recommended && value !== null;
    if (trusted) {
      current.push(observation);
      continue;
    }
    if (current.length > 0) segments.push(current);
    current = [];
  }
  if (current.length > 0) segments.push(current);
  return segments;
}

export function recoveryDomain(series?: DisturbanceSeries): [number, number] {
  const values = series?.series.flatMap((observation) =>
    [observation.recovery_p10, observation.recovery_median, observation.recovery_p90]
      .filter((value): value is number => value !== null && Number.isFinite(value)),
  ) ?? [];
  const minimum = Math.min(0, 1, ...values);
  const maximum = Math.max(0, 1, ...values);
  const span = maximum - minimum;
  const padding = Math.max(0.08, span * 0.1);
  return [minimum - padding, maximum + padding];
}

export function hasAnnualObservation(observation: AnnualObservation, metric: TimelineMetric): boolean {
  return observation.reporting_recommended && observation[metric] !== null;
}

export function isMappedTimelineYear(observationYear: number, mappedYear: number | undefined): boolean {
  return mappedYear !== undefined && observationYear === mappedYear;
}
