import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import {
  assetUrl,
  calculateBounds,
  coverageDisplay,
  coverageLabel,
  createDisturbanceSeriesLookup,
  disturbancePath,
  formatSpectralRecovery,
  imageryPath,
  loadDisturbanceTimeseries,
  parseDisturbanceCollection,
  parseDisturbanceTimeseries,
  parseSummary,
} from "./loadData";
import type { DisturbanceCollection } from "./types";

const feature = (id: string, coordinates: number[][][]): DisturbanceCollection["features"][number] => ({
  type: "Feature",
  geometry: { type: "Polygon", coordinates },
  properties: {
    disturbance_id: id,
    area_ha: 2.5,
    touches_aoi_boundary: false,
    nbr_2017_median: 0.7,
    nbr_2018_median: 0.2,
    dnbr_median: 0.5,
    recovery_2026_median: 1.22,
    recovery_2026_valid_fraction: 0.9,
    recovery_2026_coverage_status: "GOOD",
    recovery_2026_reporting_recommended: true,
  },
});

describe("static delivery helpers", () => {
  it("loads the time-series package once and returns an in-memory lookup", async () => {
    vi.stubGlobal("window", { location: { origin: "https://monitor.example" } });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: 1,
        years: [2017],
        coverage_thresholds: { good_min: 0.95, usable_min: 0.8 },
        disturbances: {
          "disturbance-001": {
            area_ha: 1,
            series: [{
              year: 2017,
              nbr_median: 0.6,
              recovery_median: 1,
              recovery_p10: 1,
              recovery_p90: 1,
              nbr_valid_fraction: 1,
              coverage_status: "GOOD",
              reporting_recommended: true,
              ndvi_median: 0.7,
              ndvi_valid_fraction: 1,
            }],
          },
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const first = await loadDisturbanceTimeseries();
    const second = await loadDisturbanceTimeseries();
    expect(first).toBe(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(first["disturbance-001"].series[0].year).toBe(2017);
    vi.unstubAllGlobals();
  });

  it("parses the generated 80-record time-series package into an ID lookup", () => {
    const generated = JSON.parse(readFileSync(new URL("../../../data/derived/web-delivery/data/disturbance-timeseries.json", import.meta.url), "utf8")) as unknown;
    const packageData = parseDisturbanceTimeseries(generated);
    const lookup = createDisturbanceSeriesLookup(packageData);
    const geography = parseDisturbanceCollection(JSON.parse(readFileSync(new URL("../../../data/derived/web-delivery/data/disturbances.geojson", import.meta.url), "utf8")) as unknown);
    expect(Object.keys(lookup)).toHaveLength(80);
    expect(Object.keys(lookup).sort()).toEqual(geography.features.map((feature) => feature.properties.disturbance_id).sort());
    expect(lookup["disturbance-001"].series.map((observation) => observation.year)).toEqual([
      2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026,
    ]);
    expect(lookup["disturbance-001"].series[9].recovery_median).toBeGreaterThan(1);
    expect(lookup["disturbance-001"].series[2].recovery_median).toBeLessThan(0);
    expect(lookup["disturbance-076"].series[5].recovery_median).toBeNull();
    expect(lookup["disturbance-004"].series.slice(5).every((observation) => observation.coverage_status === "POOR")).toBe(true);
    expect("ndvi_recovery" in lookup["disturbance-001"].series[0]).toBe(false);
  });

  it("constructs base-aware generated asset URLs", () => {
    expect(assetUrl("imagery/2018/rgb.tif", "https://monitor.example", "/app/")).toBe(
      "https://monitor.example/app/imagery/2018/rgb.tif",
    );
  });

  it("parses the summary project contract", () => {
    const summary = parseSummary({
      schema_version: 1,
      project: {
        case_study_name: "Kårböle/Ljusdal 2018 wildfire",
        disturbance_object_count: 80,
        total_analytical_disturbance_area_ha: 6808.24,
      },
      landscape_annual_series: [],
      coverage_by_year: [],
    });
    expect(summary.project.disturbance_object_count).toBe(80);
    expect(summary.project.total_analytical_disturbance_area_ha).toBe(6808.24);
  });

  it("validates stable disturbance IDs and polygon geometry", () => {
    const collection = parseDisturbanceCollection({
      type: "FeatureCollection",
      features: [feature("disturbance-001", [[[15, 61], [16, 61], [16, 62], [15, 62], [15, 61]]])],
    });
    expect(collection.features[0].properties.disturbance_id).toBe("disturbance-001");
    expect(() => parseDisturbanceCollection({
      type: "FeatureCollection",
      features: [feature("x", [[[0, 0]]]), feature("x", [[[0, 0]]])],
    })).toThrow();
  });

  it("calculates WGS84 bounds from nested polygon coordinates", () => {
    const collection = {
      type: "FeatureCollection" as const,
      features: [
        feature("one", [[[15, 61], [16, 61], [16, 62], [15, 62], [15, 61]]]),
        feature("two", [[[14, 60], [17, 60], [17, 63], [14, 63], [14, 60]]]),
      ],
    };
    expect(calculateBounds(collection)).toEqual([14, 60, 17, 63]);
  });

  it("maps coverage statuses to restrained labels", () => {
    expect(coverageLabel("GOOD")).toBe("Good coverage");
    expect(coverageLabel("USABLE_WITH_COVERAGE_FLAG")).toBe("Partial coverage");
    expect(coverageLabel("POOR")).toBe("Poor coverage");
  });

  it("does not clamp spectral recovery above one", () => {
    expect(formatSpectralRecovery(1.3451)).toBe("1.35×");
  });

  it("retains POOR values and exposes the limited-coverage warning state", () => {
    expect(formatSpectralRecovery(1.48)).toBe("1.48×");
    expect(coverageDisplay("POOR", false)).toEqual({ label: "Poor coverage", warning: true });
  });

  it("supports only the approved before and after imagery paths", () => {
    expect(imageryPath(2017)).toBe("imagery/2017/rgb.tif");
    expect(imageryPath(2018)).toBe("imagery/2018/rgb.tif");
    expect(imageryPath()).toBe("imagery/2018/rgb.tif");
    expect(() => imageryPath(2020)).toThrow();
  });

  it("supports only the fixed 2017–2018 spectral-change path", () => {
    expect(disturbancePath()).toBe("rasters/change/dnbr-2017-2018.tif");
  });
});
