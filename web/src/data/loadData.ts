import type {
  AnnualObservation,
  Coordinate,
  CoverageStatus,
  DisturbanceCollection,
  DisturbanceSeriesLookup,
  DisturbanceTimeseriesPackage,
  SummaryData,
} from "./types";

export const BEFORE_IMAGERY_YEAR = 2017;
export const AFTER_IMAGERY_YEAR = 2018;
export const SUPPORTED_IMAGERY_YEARS = [BEFORE_IMAGERY_YEAR, AFTER_IMAGERY_YEAR] as const;
export const RECOVERY_YEARS = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026] as const;
export type RecoveryYear = (typeof RECOVERY_YEARS)[number];

export function assetUrl(
  path: string,
  origin = window.location.origin,
  basePath = import.meta.env.BASE_URL,
): string {
  const cleanPath = path.replace(/^\/+/, "");
  const cleanBase = basePath.endsWith("/") ? basePath : `${basePath}/`;
  return new URL(`${cleanBase}${cleanPath}`, origin).toString();
}

export function imageryPath(year: number = AFTER_IMAGERY_YEAR): string {
  if (!SUPPORTED_IMAGERY_YEARS.includes(year as (typeof SUPPORTED_IMAGERY_YEARS)[number])) {
    throw new Error("Only 2017 and 2018 RGB imagery are supported in milestone 7B.");
  }
  return `imagery/${year}/rgb.tif`;
}

export function recoveryPath(year: number): string {
  if (!RECOVERY_YEARS.includes(year as RecoveryYear)) {
    throw new Error("Only annual spectral recovery COGs from 2017 through 2026 are supported.");
  }
  return `rasters/recovery/${year}.tif`;
}

async function fetchJson(path: string): Promise<unknown> {
  const response = await fetch(assetUrl(path));
  if (!response.ok) throw new Error(`Could not load ${path} (HTTP ${response.status}).`);
  return response.json() as Promise<unknown>;
}

export async function loadSummary(): Promise<SummaryData> {
  return parseSummary(await fetchJson("data/summary.json"));
}

export async function loadDisturbances(): Promise<DisturbanceCollection> {
  return parseDisturbanceCollection(await fetchJson("data/disturbances.geojson"));
}

let disturbanceTimeseriesPromise: Promise<DisturbanceSeriesLookup> | undefined;

export function loadDisturbanceTimeseries(): Promise<DisturbanceSeriesLookup> {
  disturbanceTimeseriesPromise ??= fetchJson("data/disturbance-timeseries.json")
    .then(parseDisturbanceTimeseries)
    .then(createDisturbanceSeriesLookup);
  return disturbanceTimeseriesPromise;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNullableFiniteNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value);
}

const coverageStatuses: CoverageStatus[] = ["GOOD", "USABLE_WITH_COVERAGE_FLAG", "POOR"];

function isCoverageStatus(value: unknown): value is CoverageStatus {
  return typeof value === "string" && coverageStatuses.includes(value as CoverageStatus);
}

export function parseSummary(value: unknown): SummaryData {
  if (!isRecord(value) || !isRecord(value.project)) {
    throw new Error("Summary data is missing its project record.");
  }
  const project = value.project;
  if (
    typeof project.case_study_name !== "string" ||
    !isFiniteNumber(project.disturbance_object_count) ||
    !isFiniteNumber(project.total_analytical_disturbance_area_ha)
  ) {
    throw new Error("Summary data has an invalid project summary.");
  }
  if (!Array.isArray(value.landscape_annual_series) || !Array.isArray(value.coverage_by_year)) {
    throw new Error("Summary data is missing its annual series.");
  }
  return value as unknown as SummaryData;
}

export function parseDisturbanceCollection(value: unknown): DisturbanceCollection {
  if (!isRecord(value) || value.type !== "FeatureCollection" || !Array.isArray(value.features)) {
    throw new Error("Disturbance data is not a FeatureCollection.");
  }
  const ids = new Set<string>();
  for (const feature of value.features) {
    if (!isRecord(feature) || feature.type !== "Feature" || !isRecord(feature.properties)) {
      throw new Error("Disturbance data contains an invalid feature.");
    }
    const properties = feature.properties;
    if (
      typeof properties.disturbance_id !== "string" ||
      properties.disturbance_id.length === 0 ||
      ids.has(properties.disturbance_id) ||
      !isRecord(feature.geometry) ||
      (feature.geometry.type !== "Polygon" && feature.geometry.type !== "MultiPolygon")
    ) {
      throw new Error("Disturbance data contains an invalid or duplicate disturbance ID.");
    }
    ids.add(properties.disturbance_id);
    const numericFields = [
      "area_ha",
      "nbr_2017_median",
      "nbr_2018_median",
      "dnbr_median",
      "recovery_2026_median",
      "recovery_2026_valid_fraction",
    ];
    if (numericFields.some((field) => !isFiniteNumber(properties[field]))) {
      throw new Error(`Disturbance ${properties.disturbance_id} has invalid numeric properties.`);
    }
    if (!isCoverageStatus(properties.recovery_2026_coverage_status)) {
      throw new Error(`Disturbance ${properties.disturbance_id} has an invalid coverage status.`);
    }
  }
  return value as unknown as DisturbanceCollection;
}

export function parseDisturbanceTimeseries(value: unknown): DisturbanceTimeseriesPackage {
  if (
    !isRecord(value) ||
    !isFiniteNumber(value.schema_version) ||
    !Array.isArray(value.years) ||
    !isRecord(value.coverage_thresholds) ||
    !isRecord(value.disturbances)
  ) {
    throw new Error("Time-series data has an invalid package structure.");
  }

  if (
    value.years.some((year) => !Number.isInteger(year)) ||
    value.years.length === 0 ||
    !isFiniteNumber(value.coverage_thresholds.good_min) ||
    !isFiniteNumber(value.coverage_thresholds.usable_min)
  ) {
    throw new Error("Time-series data has invalid years or coverage thresholds.");
  }

  const years = value.years as number[];
  for (const [disturbanceId, rawSeries] of Object.entries(value.disturbances)) {
    if (!isRecord(rawSeries) || !isFiniteNumber(rawSeries.area_ha) || !Array.isArray(rawSeries.series)) {
      throw new Error(`Time-series record ${disturbanceId} is invalid.`);
    }
    if (rawSeries.series.length !== years.length) {
      throw new Error(`Time-series record ${disturbanceId} does not contain one observation per year.`);
    }
    rawSeries.series.forEach((rawObservation, index) => {
      if (!isAnnualObservation(rawObservation) || rawObservation.year !== years[index]) {
        throw new Error(`Time-series record ${disturbanceId} has invalid year ${String(rawObservation)}.`);
      }
    });
  }
  return value as unknown as DisturbanceTimeseriesPackage;
}

function isAnnualObservation(value: unknown): value is AnnualObservation {
  return (
    isRecord(value) &&
    Number.isInteger(value.year) &&
    isNullableFiniteNumber(value.nbr_median) &&
    isNullableFiniteNumber(value.recovery_median) &&
    isNullableFiniteNumber(value.recovery_p10) &&
    isNullableFiniteNumber(value.recovery_p90) &&
    isFiniteNumber(value.nbr_valid_fraction) &&
    isCoverageStatus(value.coverage_status) &&
    typeof value.reporting_recommended === "boolean" &&
    isNullableFiniteNumber(value.ndvi_median) &&
    isFiniteNumber(value.ndvi_valid_fraction)
  );
}

export function createDisturbanceSeriesLookup(
  packageData: DisturbanceTimeseriesPackage,
): DisturbanceSeriesLookup {
  return { ...packageData.disturbances };
}

export function calculateBounds(collection: DisturbanceCollection): [number, number, number, number] {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;

  const visit = (coordinates: Coordinate): void => {
    if (typeof coordinates[0] === "number") {
      const [longitude, latitude] = coordinates as number[];
      west = Math.min(west, longitude);
      south = Math.min(south, latitude);
      east = Math.max(east, longitude);
      north = Math.max(north, latitude);
      return;
    }
    for (const child of coordinates as Coordinate[]) visit(child);
  };

  for (const feature of collection.features) visit(feature.geometry.coordinates);
  if (![west, south, east, north].every(Number.isFinite)) throw new Error("Disturbance data has no coordinates.");
  return [west, south, east, north];
}

export function coverageLabel(status: CoverageStatus): string {
  return {
    GOOD: "Good coverage",
    USABLE_WITH_COVERAGE_FLAG: "Partial coverage",
    POOR: "Poor coverage",
  }[status];
}

export function coverageShortLabel(status: CoverageStatus): string {
  return status === "GOOD" ? "Good" : status === "POOR" ? "Poor" : "Partial";
}

export function coverageDisplay(status: CoverageStatus, reportingRecommended: boolean): {
  label: string;
  warning: boolean;
} {
  return { label: coverageLabel(status), warning: !reportingRecommended };
}

export function formatSpectralRecovery(value: number): string {
  return `${value.toFixed(2)}×`;
}

export function observationForYear(series: { series: AnnualObservation[] } | undefined, year: number): AnnualObservation | undefined {
  return series?.series.find((observation) => observation.year === year);
}
