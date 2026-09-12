import { describe, expect, it } from "vitest";
import {
  DISTURBANCE_ALPHA,
  DISTURBANCE_COLOR_STOPS,
  DISTURBANCE_DETECTION_THRESHOLD,
  disturbanceColorFunction,
  interpolateDisturbanceColor,
} from "./disturbanceColor";

function hexRgb(hex: string): [number, number, number] {
  return [Number.parseInt(hex.slice(1, 3), 16), Number.parseInt(hex.slice(3, 5), 16), Number.parseInt(hex.slice(5, 7), 16)];
}

describe("2017–2018 dNBR display color", () => {
  it.each(DISTURBANCE_COLOR_STOPS.map((stop) => [stop.value, hexRgb(stop.color)] as const))("uses the approved display stop at %s", (value, expected) => {
    expect(interpolateDisturbanceColor(value)).toEqual(expected);
  });

  it("keeps raw values unchanged while clamping only display endpoints", () => {
    const above = new Float32Array([1.26]);
    const below = new Float32Array([-0.9]);
    const aboveColor = new Uint8ClampedArray(4);
    const belowColor = new Uint8ClampedArray(4);
    disturbanceColorFunction(above, aboveColor, { offset: 0, scale: 1, noData: -9999 });
    disturbanceColorFunction(below, belowColor, { offset: 0, scale: 1, noData: -9999 });
    expect(Array.from(aboveColor)).toEqual([...hexRgb("#6b3d30"), DISTURBANCE_ALPHA.maximum]);
    expect(Array.from(belowColor)).toEqual([...hexRgb("#466f6b"), DISTURBANCE_ALPHA.quiet]);
    expect(above[0]).toBeCloseTo(1.26);
    expect(below[0]).toBeCloseTo(-0.9);
  });

  it("uses the threshold and value-dependent display alpha", () => {
    expect(DISTURBANCE_DETECTION_THRESHOLD).toBe(0.3);
    const values = [-0.4, 0, 0.3, 0.6, 1];
    const alphas = values.map((value) => {
      const color = new Uint8ClampedArray(4);
      disturbanceColorFunction(new Float32Array([value]), color, { offset: 0, scale: 1, noData: -9999 });
      return color[3];
    });
    expect(alphas).toEqual([DISTURBANCE_ALPHA.quiet, DISTURBANCE_ALPHA.quiet, DISTURBANCE_ALPHA.threshold, DISTURBANCE_ALPHA.strong, DISTURBANCE_ALPHA.maximum]);
  });

  it("renders missing and non-finite pixels transparent", () => {
    for (const value of [-9999, Number.NaN]) {
      const color = new Uint8ClampedArray(4);
      disturbanceColorFunction(new Float32Array([value]), color, { offset: 0, scale: 1, noData: -9999 });
      expect(Array.from(color)).toEqual([0, 0, 0, 0]);
    }
  });
});
