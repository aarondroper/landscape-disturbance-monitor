import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const headerSource = readFileSync(new URL("./AppHeader.tsx", import.meta.url), "utf8");

describe("application header contract", () => {
  it("keeps the product mark and title in the header", () => {
    expect(headerSource).toContain('className="brand-mark"');
    expect(headerSource).toContain("Landscape Disturbance Monitor");
  });

  it("keeps the three existing map modes in the tab control", () => {
    expect(headerSource).toContain("MAP_VIEW_MODES.map");
    expect(headerSource).toContain('role="tablist"');
    expect(headerSource).toContain('role="tab"');
  });
});
