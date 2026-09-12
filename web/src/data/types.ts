export type Coordinate = number[] | Coordinate[];

export interface PolygonGeometry {
  type: "Polygon" | "MultiPolygon";
  coordinates: Coordinate[];
}

export interface DisturbanceProperties {
  disturbance_id: string;
  area_ha: number;
  touches_aoi_boundary: boolean;
  nbr_2017_median: number;
  nbr_2018_median: number;
  dnbr_median: number;
  recovery_2026_median: number;
  recovery_2026_valid_fraction: number;
  recovery_2026_coverage_status: CoverageStatus;
  recovery_2026_reporting_recommended: boolean;
}

export interface DisturbanceFeature {
  type: "Feature";
  geometry: PolygonGeometry;
  properties: DisturbanceProperties;
}

export interface DisturbanceCollection {
  type: "FeatureCollection";
  features: DisturbanceFeature[];
}

export type CoverageStatus = "GOOD" | "USABLE_WITH_COVERAGE_FLAG" | "POOR";

export interface SummaryProject {
  case_study_identifier: string;
  case_study_name: string;
  annual_years: number[];
  benchmark_imagery_years: number[];
  disturbance_object_count: number;
  total_analytical_disturbance_area_ha: number;
  primary_indicator: string;
  secondary_indicator: string;
  recovery_metric: string;
}

export interface SummaryAnnualRecord {
  year: number;
  nbr_median: number;
  recovery_median: number;
  recovery_p10: number;
  recovery_p90: number;
  nbr_valid_fraction: number;
  fraction_ge_050: number;
  fraction_ge_080: number;
  fraction_ge_100: number;
  fraction_lt_000: number;
  fraction_gt_100: number;
  ndvi_median: number;
  ndvi_valid_fraction: number;
}

export interface SummaryCoverageRecord {
  year: number;
  GOOD: number;
  USABLE_WITH_COVERAGE_FLAG: number;
  POOR: number;
  zero_valid_count: number;
}

export interface SummaryData {
  schema_version: number;
  project: SummaryProject;
  landscape_annual_series: SummaryAnnualRecord[];
  coverage_by_year: SummaryCoverageRecord[];
  current_2026: {
    recovery_median: number;
    nbr_valid_fraction: number;
    fraction_ge_080: number;
    fraction_ge_100: number;
  };
  limitation_flags: {
    spectral_not_ecological_recovery: boolean;
    later_year_coverage_varies: boolean;
    missing_values_interpolated: boolean;
  };
}
