import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { RECOVERY_FORMULA, methodologySections, SOURCE_ATTRIBUTION } from "./methodologyContent";
import { EMPTY_SELECTION_PRIMARY, EMPTY_SELECTION_SECONDARY } from "./DisturbanceDetails";
import { methodologyPanelReducer } from "./methodologyPanelState";

const methodologyText = methodologySections.flatMap((section) => [
  ...(section.paragraphs ?? []),
  ...(section.bullets ?? []),
  section.formula ?? "",
  ...(section.definitions?.flatMap((definition) => [definition.label, definition.description]) ?? []),
]).join(" ");

describe("methodology panel contract", () => {
  it("opens and closes through the panel state actions", () => {
    expect(methodologyPanelReducer(false, { type: "open" })).toBe(true);
    expect(methodologyPanelReducer(true, { type: "close" })).toBe(false);
  });

  it("closes on Escape", () => {
    expect(methodologyPanelReducer(true, { type: "keydown", key: "Escape" })).toBe(false);
    expect(methodologyPanelReducer(true, { type: "keydown", key: "Enter" })).toBe(true);
  });

  it("keeps the recovery formula exact", () => {
    expect(RECOVERY_FORMULA).toBe("recovery_y = (NBR_y − NBR_2018) / (NBR_2017 − NBR_2018)");
  });

  it("documents the disturbance rule and retained-area threshold", () => {
    expect(methodologyText).toContain("NBR2017 > 0.30");
    expect(methodologyText).toContain("dNBR ≥ 0.30");
    expect(methodologyText).toContain("connected retained area ≥ 5 ha");
    expect(methodologyText).toContain("not an authoritative wildfire perimeter or burn-severity classification");
  });

  it("explains spectral boundaries, coverage thresholds, and limitations", () => {
    expect(methodologyText).toContain("NBR exceeds the 2017 spectral baseline");
    expect(methodologyText).toContain("NBR is below the 2018 state");
    expect(methodologyText).toContain("Good: ≥95% valid object pixels");
    expect(methodologyText).toContain("Partial: ≥80% and <95%");
    expect(methodologyText).toContain("Poor: <80%");
    expect(methodologyText).toContain("Missing annual pixels are not interpolated or filled");
    expect(methodologyText).toContain("Spectral recovery is not the same as ecological recovery.");
    expect(methodologyText).toContain("Spectral indices are proxies, not direct ecological measurements.");
  });

  it("keeps source attribution and the empty selection invitation concise", () => {
    expect(methodologyText).toContain("Copernicus Sentinel-2 Level-2A");
    expect(methodologyText).toContain("Element 84 Earth Search");
    expect(SOURCE_ATTRIBUTION).toBe("Sentinel-2 L2A · Copernicus · via Element 84 Earth Search");
    expect(EMPTY_SELECTION_PRIMARY).toBe("Select a disturbance area to inspect its spectral trajectory.");
    expect(EMPTY_SELECTION_SECONDARY).toBe("Hover or click a detected disturbance polygon.");
  });

  it("sets the page metadata and reduced-motion rule", () => {
    const html = readFileSync(new URL("../../index.html", import.meta.url), "utf8");
    const css = readFileSync(new URL("../styles/app.css", import.meta.url), "utf8");
    expect(html).toContain("<title>Landscape Disturbance Monitor</title>");
    expect(html).toContain('name="description"');
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
