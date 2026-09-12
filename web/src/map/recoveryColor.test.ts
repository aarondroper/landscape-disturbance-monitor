import { describe, expect, it } from "vitest";
import { RECOVERY_ALPHA, recoveryColorFunction, interpolateRecoveryColor } from "./recoveryColor";

describe("annual recovery display color", () => {
  it.each([
    [0, [107, 76, 59]],
    [0.5, [199, 166, 107]],
    [1, [111, 170, 161]],
  ])("interpolates the semantic stop at %s", (value, expected) => {
    expect(interpolateRecoveryColor(value)).toEqual(expected);
  });

  it("clamps only the display color at the endpoint and preserves raw pixels", () => {
    const pixel = new Float32Array([2.4]);
    const color = new Uint8ClampedArray(4);
    recoveryColorFunction(pixel, color, { offset: 0, scale: 1, noData: -9999 });
    expect(Array.from(color)).toEqual([47, 111, 104, RECOVERY_ALPHA]);
    expect(pixel[0]).toBeCloseTo(2.4);
  });

  it("makes nodata transparent while leaving valid unbounded values untouched", () => {
    const pixel = new Float32Array([-9999]);
    const color = new Uint8ClampedArray(4);
    recoveryColorFunction(pixel, color, { offset: 0, scale: 1, noData: -9999 });
    expect(Array.from(color)).toEqual([0, 0, 0, 0]);
  });
});
