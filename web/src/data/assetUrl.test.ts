import { afterEach, describe, expect, it, vi } from "vitest";
import { assetUrl, resolveGeoAssetBaseUrl } from "./assetUrl";

afterEach(() => vi.unstubAllGlobals());

describe("geospatial asset URL resolution", () => {
  it("uses /geo/ by default for local development", () => {
    vi.stubGlobal("window", { location: { origin: "http://127.0.0.1:5173" } });
    expect(assetUrl("data/summary.json")).toBe("http://127.0.0.1:5173/geo/data/summary.json");
  });

  it("supports an absolute production base and all generated asset families", () => {
    const base = "https://assets.example.com/landscape-disturbance-monitor/";
    expect(assetUrl("imagery/2018/rgb.tif", base)).toBe(`${base}imagery/2018/rgb.tif`);
    expect(assetUrl("rasters/recovery/2026.tif", base)).toBe(`${base}rasters/recovery/2026.tif`);
    expect(assetUrl("rasters/change/dnbr-2017-2018.tif", base)).toBe(`${base}rasters/change/dnbr-2017-2018.tif`);
    expect(assetUrl("data/disturbances.geojson", base)).toBe(`${base}data/disturbances.geojson`);
    expect(assetUrl("data/disturbance-timeseries.json", base)).toBe(`${base}data/disturbance-timeseries.json`);
  });

  it("normalizes trailing and repeated slashes without corrupting the URL", () => {
    expect(resolveGeoAssetBaseUrl("/geo")).toBe("/geo/");
    expect(resolveGeoAssetBaseUrl("https://assets.example.com//project//")).toBe("https://assets.example.com/project/");
    expect(assetUrl("/imagery//2018/rgb.tif", "https://assets.example.com/project//")).toBe(
      "https://assets.example.com/project/imagery/2018/rgb.tif",
    );
    expect(assetUrl("data/file%20name.json", "https://assets.example.com/project")).toBe(
      "https://assets.example.com/project/data/file%20name.json",
    );
  });

  it("rejects malformed or unsafe asset-base configuration", () => {
    expect(() => resolveGeoAssetBaseUrl("assets.example.com/project/")).toThrow(/valid URL/);
    expect(() => resolveGeoAssetBaseUrl("//assets.example.com/project/")).toThrow(/root-relative/);
    expect(() => resolveGeoAssetBaseUrl("http://assets.example.com/project/")).toThrow(/HTTPS/);
    expect(() => resolveGeoAssetBaseUrl("https://user:pass@assets.example.com/project/")).toThrow(/credentials/);
    expect(() => assetUrl("data/%2e%2e/private.json", "/geo/")).toThrow(/traverse/);
  });

  it("wraps external COG URLs with the MapLibre cog protocol format", () => {
    const url = assetUrl("rasters/recovery/2026.tif", "https://assets.example.com/project/");
    expect(`cog://${url}`).toBe("cog://https://assets.example.com/project/rasters/recovery/2026.tif");
  });
});
