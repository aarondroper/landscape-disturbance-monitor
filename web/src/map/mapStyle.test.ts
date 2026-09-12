import { describe, expect, it } from "vitest";
import { localMapStyle } from "./mapStyle";

describe("initial local map style", () => {
  it("has no external sources, sprites, glyphs, or API-key requirement", () => {
    expect(localMapStyle.sources).toEqual({});
    expect(localMapStyle.sprite).toBeUndefined();
    expect(localMapStyle.glyphs).toBeUndefined();
    expect(JSON.stringify(localMapStyle)).not.toMatch(/https?:\/\//);
  });
});
