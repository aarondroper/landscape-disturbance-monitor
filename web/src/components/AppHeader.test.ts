import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { MAP_VIEW_MODES } from "../map/viewMode";
import { AppHeader } from "./AppHeader";

const headerSource = readFileSync(new URL("./AppHeader.tsx", import.meta.url), "utf8");

describe("application header contract", () => {
  it("keeps the product mark and title in the header", () => {
    expect(headerSource).toContain('className="app-logo brand-mark"');
    expect(headerSource).toContain("Landscape Disturbance Monitor");
  });

  it("keeps the three existing map modes in the tab control", () => {
    expect(headerSource).toContain("MAP_VIEW_MODES.map");
    expect(headerSource).toContain('role="tablist"');
    expect(headerSource).toContain('role="tab"');
  });

  it.each(MAP_VIEW_MODES)("renders an enabled shared boundary control in %s mode", (mode) => {
    const markup = renderToStaticMarkup(createElement(AppHeader, {
      mode,
      onModeChange: () => undefined,
      disturbanceBoundariesVisible: false,
      onDisturbanceBoundariesVisibleChange: () => undefined,
      methodologyButtonRef: { current: null },
      onMethodology: () => undefined,
    }));
    const checkbox = markup.match(/<input[^>]*type="checkbox"[^>]*>/)?.[0];
    expect(checkbox).toBeDefined();
    expect(checkbox).toContain('aria-label="Disturbance boundaries"');
    expect(checkbox).not.toContain("disabled");
  });

  it.each([true, false])("reflects shared visibility state without disabling the control (%s)", (visible) => {
    const markup = renderToStaticMarkup(createElement(AppHeader, {
      mode: "compare",
      onModeChange: () => undefined,
      disturbanceBoundariesVisible: visible,
      onDisturbanceBoundariesVisibleChange: () => undefined,
      methodologyButtonRef: { current: null },
      onMethodology: () => undefined,
    }));
    const checkbox = markup.match(/<input[^>]*type="checkbox"[^>]*>/)?.[0] ?? "";
    expect(checkbox.includes('checked=""')).toBe(visible);
    expect(checkbox).not.toContain("disabled");
  });
});
