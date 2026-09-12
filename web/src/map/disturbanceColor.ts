export const DISTURBANCE_ALPHA = {
  quiet: 88,
  threshold: 166,
  strong: 220,
  maximum: 228,
} as const;

export const DISTURBANCE_COLOR_STOPS = [
  { value: -0.4, color: "#466f6b" },
  { value: 0, color: "#d8d4c6" },
  { value: 0.3, color: "#d3ad62" },
  { value: 0.6, color: "#a76545" },
  { value: 1, color: "#6b3d30" },
] as const;

export const DISTURBANCE_DISPLAY_MIN = DISTURBANCE_COLOR_STOPS[0].value;
export const DISTURBANCE_DISPLAY_MAX = DISTURBANCE_COLOR_STOPS[DISTURBANCE_COLOR_STOPS.length - 1].value;
export const DISTURBANCE_DETECTION_THRESHOLD = 0.3;

export type Rgb = [number, number, number];
type TypedArray = Uint8Array | Int8Array | Uint16Array | Int16Array | Uint32Array | Int32Array | Float32Array | Float64Array;
type ColorFunction = (pixel: TypedArray, color: Uint8ClampedArray, metadata: { offset: number; scale: number; noData?: number }) => void;

function rgbFromHex(hex: string): Rgb {
  return [
    Number.parseInt(hex.slice(1, 3), 16),
    Number.parseInt(hex.slice(3, 5), 16),
    Number.parseInt(hex.slice(5, 7), 16),
  ];
}

function mix(left: Rgb, right: Rgb, amount: number): Rgb {
  return left.map((channel, index) => Math.round(channel + (right[index] - channel) * amount)) as Rgb;
}

export function interpolateDisturbanceColor(value: number): Rgb {
  if (value <= DISTURBANCE_DISPLAY_MIN) return rgbFromHex(DISTURBANCE_COLOR_STOPS[0].color);
  if (value >= DISTURBANCE_DISPLAY_MAX) return rgbFromHex(DISTURBANCE_COLOR_STOPS[DISTURBANCE_COLOR_STOPS.length - 1].color);

  for (let index = 1; index < DISTURBANCE_COLOR_STOPS.length; index += 1) {
    const upper = DISTURBANCE_COLOR_STOPS[index];
    const lower = DISTURBANCE_COLOR_STOPS[index - 1];
    if (value <= upper.value) {
      const amount = (value - lower.value) / (upper.value - lower.value);
      return mix(rgbFromHex(lower.color), rgbFromHex(upper.color), amount);
    }
  }
  return rgbFromHex(DISTURBANCE_COLOR_STOPS[DISTURBANCE_COLOR_STOPS.length - 1].color);
}

function interpolateAlpha(value: number): number {
  if (value <= 0) return DISTURBANCE_ALPHA.quiet;
  if (value <= DISTURBANCE_DETECTION_THRESHOLD) {
    return Math.round(DISTURBANCE_ALPHA.quiet + (DISTURBANCE_ALPHA.threshold - DISTURBANCE_ALPHA.quiet) * (value / DISTURBANCE_DETECTION_THRESHOLD));
  }
  if (value <= 0.6) {
    return Math.round(DISTURBANCE_ALPHA.threshold + (DISTURBANCE_ALPHA.strong - DISTURBANCE_ALPHA.threshold) * ((value - DISTURBANCE_DETECTION_THRESHOLD) / 0.3));
  }
  return Math.round(DISTURBANCE_ALPHA.strong + (DISTURBANCE_ALPHA.maximum - DISTURBANCE_ALPHA.strong) * Math.min((value - 0.6) / 0.4, 1));
}

export const disturbanceColorFunction: ColorFunction = (pixel, color, metadata) => {
  const rawValue = pixel[0];
  const value = rawValue * metadata.scale + metadata.offset;
  if (rawValue === metadata.noData || !Number.isFinite(value)) {
    color.set([0, 0, 0, 0]);
    return;
  }
  color.set([...interpolateDisturbanceColor(value), interpolateAlpha(value)]);
};
