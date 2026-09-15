import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { MAP_VIEW_MODES } from "../map/viewMode";
import { AppHeader } from "./AppHeader";

const headerSource = readFileSync(new URL("./AppHeader.tsx", import.meta.url), "utf8");
const logoAsset = readFileSync(new URL("../../public/app-logo.svg", import.meta.url), "utf8");

describe("application header contract", () => {
  it("renders the replaceable logo asset as a decorative mark beside the title", () => {
    const markup = renderToStaticMarkup(createElement(AppHeader, {
      mode: "compare",
      onModeChange: () => undefined,
      disturbanceBoundariesVisible: true,
      onDisturbanceBoundariesVisibleChange: () => undefined,
      methodologyButtonRef: { current: null },
      onMethodology: () => undefined,
    }));
    const logo = markup.match(/<img[^>]*>/)?.[0] ?? "";
    expect(headerSource).toContain('className="app-logo-slot"');
    expect(markup).toContain('<div class="app-logo-slot" aria-hidden="true">');
    expect(logo).toContain('class="app-logo"');
    expect(logo).toContain('src="/app-logo.svg"');
    expect(logo).toContain('alt=""');
    expect(markup).toContain("Landscape Disturbance Monitor");
  });

  it("keeps the current header context and project summary status", () => {
    const markup = renderToStaticMarkup(createElement(AppHeader, {
      mode: "compare",
      summaryError: "Project summary unavailable",
      onModeChange: () => undefined,
      disturbanceBoundariesVisible: true,
      onDisturbanceBoundariesVisibleChange: () => undefined,
      methodologyButtonRef: { current: null },
      onMethodology: () => undefined,
    }));
    expect(markup).toContain("Hälsingland, Sweden · 2017–2026");
    expect(markup).toContain("Project summary unavailable");
    expect(markup).toContain("Methodology");
  });

  it("keeps the placeholder lightweight and text-free", () => {
    expect(logoAsset.trimStart()).toMatch(/^<svg\b/);
    expect(logoAsset).not.toMatch(/<text\b/i);
    expect(logoAsset.length).toBeLessThan(2048);
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
