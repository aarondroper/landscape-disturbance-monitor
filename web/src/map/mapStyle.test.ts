import { describe, expect, it } from "vitest";
import { localMapStyle, MAP_CANVAS_BACKGROUND_COLOR } from "./mapStyle";

describe("shared local map canvas style", () => {
  it("uses the intentional dark no-data canvas across every map mode", () => {
    expect(MAP_CANVAS_BACKGROUND_COLOR).toBe("#2b3733");
    expect(localMapStyle.layers).toContainEqual({
      id: "local-background",
      type: "background",
      paint: { "background-color": MAP_CANVAS_BACKGROUND_COLOR },
    });
  });

  it("has no external sources, sprites, glyphs, or API-key requirement", () => {
    expect(localMapStyle.sources).toEqual({});
    expect(localMapStyle.sprite).toBeUndefined();
    expect(localMapStyle.glyphs).toBeUndefined();
    expect(JSON.stringify(localMapStyle)).not.toMatch(/https?:\/\//);
  });
});
