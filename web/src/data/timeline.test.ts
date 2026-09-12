import { describe, expect, it } from "vitest";
import { buildTrustedSegments, recoveryDomain } from "./timeline";
import type { AnnualObservation, DisturbanceSeries } from "./types";

function observation(year: number, overrides: Partial<AnnualObservation> = {}): AnnualObservation {
  return {
    year,
    nbr_median: 0.5,
    recovery_median: 0.5,
    recovery_p10: 0.2,
    recovery_p90: 0.8,
    nbr_valid_fraction: 0.95,
    coverage_status: "GOOD",
    reporting_recommended: true,
    ndvi_median: 0.4,
    ndvi_valid_fraction: 0.8,
    ...overrides,
  };
}

describe("trajectory helpers", () => {
  it("breaks trusted trajectory segments at POOR and missing observations", () => {
    const series = [
      observation(2017),
      observation(2018),
      observation(2019, { coverage_status: "POOR" }),
      observation(2020),
      observation(2021, { recovery_median: null, reporting_recommended: false }),
      observation(2022),
    ];
    expect(buildTrustedSegments(series, "recovery_median").map((segment) => segment.map((item) => item.year))).toEqual([
      [2017, 2018],
      [2020],
      [2022],
    ]);
    expect(buildTrustedSegments(series, "nbr_median").map((segment) => segment.map((item) => item.year))).toEqual([
      [2017, 2018],
      [2020],
      [2022],
    ]);
  });

  it("includes zero and one in the adaptive recovery domain without clamping", () => {
    const series: DisturbanceSeries = {
      area_ha: 1,
      series: [observation(2017, { recovery_median: -0.45, recovery_p10: -0.8, recovery_p90: 1.7 })],
    };
    const [minimum, maximum] = recoveryDomain(series);
    expect(minimum).toBeLessThan(-0.45);
    expect(maximum).toBeGreaterThan(1.7);
    expect(minimum).toBeLessThanOrEqual(0);
    expect(maximum).toBeGreaterThanOrEqual(1);
  });

  it("handles all-null and partial series safely", () => {
    const series: DisturbanceSeries = {
      area_ha: 1,
      series: [
        observation(2017, { nbr_median: null, recovery_median: null, recovery_p10: null, recovery_p90: null, reporting_recommended: false }),
        observation(2018, { recovery_median: 1.4, recovery_p10: 1.1, recovery_p90: 1.6 }),
      ],
    };
    expect(buildTrustedSegments(series.series, "recovery_median").map((segment) => segment.map((item) => item.year))).toEqual([[2018]]);
    expect(recoveryDomain({ area_ha: 1, series: [observation(2017, { recovery_median: null, recovery_p10: null, recovery_p90: null })] })).toEqual([-0.1, 1.1]);
  });
});
