import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  createDisturbanceSeriesLookup,
  parseDisturbanceCollection,
  parseDisturbanceTimeseries,
} from "./loadData";

const generatedRoot = new URL("../../../data/derived/web-delivery/data/", import.meta.url);

describe("generated delivery package", () => {
  it("parses the real 80-record time-series and matches generated geography", () => {
    const packageData = parseDisturbanceTimeseries(
      JSON.parse(readFileSync(new URL("disturbance-timeseries.json", generatedRoot), "utf8")) as unknown,
    );
    const lookup = createDisturbanceSeriesLookup(packageData);
    const geography = parseDisturbanceCollection(
      JSON.parse(readFileSync(new URL("disturbances.geojson", generatedRoot), "utf8")) as unknown,
    );
    expect(Object.keys(lookup)).toHaveLength(80);
    expect(Object.keys(lookup).sort()).toEqual(
      geography.features.map((feature) => feature.properties.disturbance_id).sort(),
    );
    expect(lookup["disturbance-001"].series.map((observation) => observation.year)).toEqual([
      2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026,
    ]);
    expect(lookup["disturbance-001"].series[9].recovery_median).toBeGreaterThan(1);
    expect(lookup["disturbance-001"].series[2].recovery_median).toBeLessThan(0);
    expect(lookup["disturbance-076"].series[5].recovery_median).toBeNull();
    expect(
      lookup["disturbance-004"].series
        .slice(5)
        .every((observation) => observation.coverage_status === "POOR"),
    ).toBe(true);
    expect("ndvi_recovery" in lookup["disturbance-001"].series[0]).toBe(false);
  });
});
