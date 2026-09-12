import { describe, expect, it, vi } from "vitest";
import { coverageShortLabel, observationForYear, RECOVERY_YEARS, recoveryPath } from "../data/loadData";
import { isMappedTimelineYear } from "../data/timeline";
import type { DisturbanceSeries } from "../data/types";
import { cameraSnapshotOf, sameCameraSnapshot, type CameraSnapshot } from "./camera";
import { recoveryCogUrl, recoveryLayer, recoverySource, recoverySourceId } from "./mapLayers";
import { DEFAULT_MAP_MODE, DEFAULT_RECOVERY_YEAR, MAP_VIEW_MODES, type MapViewMode } from "./viewMode";

const series: DisturbanceSeries = {
  area_ha: 1,
  series: RECOVERY_YEARS.map((year) => ({
    year,
    nbr_median: 0.5,
    recovery_median: year === 2023 ? null : year / 2000,
    recovery_p10: 0,
    recovery_p90: 1,
    nbr_valid_fraction: year === 2023 ? 0.4 : 0.95,
    coverage_status: year === 2023 ? "POOR" : "GOOD",
    reporting_recommended: year !== 2023,
    ndvi_median: null,
    ndvi_valid_fraction: 0,
  })),
};

describe("recovery map configuration", () => {
  it("supports exactly Compare, Disturbance, and Recovery modes", () => {
    const modes: MapViewMode[] = [...MAP_VIEW_MODES];
    expect(modes).toEqual(["compare", "disturbance", "recovery"]);
  });

  it("defaults to Compare and recovery year 2026", () => {
    expect(DEFAULT_MAP_MODE).toBe("compare");
    expect(DEFAULT_RECOVERY_YEAR).toBe(2026);
  });

  it("supports exactly the ten annual recovery years", () => {
    expect(RECOVERY_YEARS).toEqual([2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]);
  });

  it.each(RECOVERY_YEARS)("generates the direct browser COG path for %s", (year) => {
    vi.stubGlobal("window", { location: { origin: "https://monitor.example" } });
    expect(recoveryPath(year)).toBe(`rasters/recovery/${year}.tif`);
    expect(recoveryCogUrl(year)).toBe(`https://monitor.example/geo/rasters/recovery/${year}.tif`);
    expect(recoverySource(year)).toMatchObject({ type: "raster", url: `cog://https://monitor.example/geo/rasters/recovery/${year}.tif`, tileSize: 256 });
    expect(recoverySourceId(year)).toBe(`recovery-${year}`);
    expect(recoveryLayer(year).type).toBe("raster");
    vi.unstubAllGlobals();
  });

  it("rejects unsupported recovery years", () => {
    expect(() => recoveryPath(2016)).toThrow();
    expect(() => recoveryPath(2027)).toThrow();
  });

  it("keeps analytical paths scoped to recovery COGs only", () => {
    const serialized = JSON.stringify(RECOVERY_YEARS.map(recoveryPath));
    expect(serialized).not.toMatch(/nbr|dnbr/i);
  });

  it("does not alter or clamp time-series values when looking up a mapped year", () => {
    expect(observationForYear(series, 2026)?.recovery_median).toBe(1.013);
    expect(observationForYear(series, 2023)?.recovery_median).toBeNull();
    expect(observationForYear(series, 2016)).toBeUndefined();
  });

  it("maps selected-year coverage and retains the POOR label", () => {
    expect(observationForYear(series, 2023)?.coverage_status).toBe("POOR");
    expect(coverageShortLabel("POOR")).toBe("Poor");
  });

  it("highlights only the active timeline year", () => {
    expect(isMappedTimelineYear(2023, 2023)).toBe(true);
    expect(isMappedTimelineYear(2022, 2023)).toBe(false);
    expect(isMappedTimelineYear(2023, undefined)).toBe(false);
  });

  it("captures and compares a camera snapshot without resetting it", () => {
    const map = {
      getCenter: () => ({ lng: 15.2, lat: 61.7 }),
      getZoom: () => 9.5,
      getBearing: () => 0,
      getPitch: () => 0,
    };
    const snapshot = cameraSnapshotOf(map);
    const equivalent: CameraSnapshot = { center: [15.2, 61.7], zoom: 9.5, bearing: 0, pitch: 0 };
    expect(sameCameraSnapshot(snapshot, equivalent)).toBe(true);
  });
});
