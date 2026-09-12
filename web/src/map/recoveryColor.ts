export const RECOVERY_ALPHA = 224;

export const RECOVERY_COLOR_STOPS = [
  { value: 0, color: "#6b4c3b" },
  { value: 0.5, color: "#c7a66b" },
  { value: 1, color: "#6faaa1" },
  { value: 1.5, color: "#2f6f68" },
] as const;

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

export function interpolateRecoveryColor(value: number): Rgb {
  if (value <= RECOVERY_COLOR_STOPS[0].value) return rgbFromHex(RECOVERY_COLOR_STOPS[0].color);
  const last = RECOVERY_COLOR_STOPS[RECOVERY_COLOR_STOPS.length - 1];
  if (value >= last.value) return rgbFromHex(last.color);

  for (let index = 1; index < RECOVERY_COLOR_STOPS.length; index += 1) {
    const upper = RECOVERY_COLOR_STOPS[index];
    const lower = RECOVERY_COLOR_STOPS[index - 1];
    if (value <= upper.value) {
      const amount = (value - lower.value) / (upper.value - lower.value);
      return mix(rgbFromHex(lower.color), rgbFromHex(upper.color), amount);
    }
  }
  return rgbFromHex(last.color);
}

export const recoveryColorFunction: ColorFunction = (pixel, color, metadata) => {
  const rawValue = pixel[0];
  const value = rawValue * metadata.scale + metadata.offset;
  if (rawValue === metadata.noData || !Number.isFinite(value)) {
    color.set([0, 0, 0, 0]);
    return;
  }
  color.set([...interpolateRecoveryColor(value), RECOVERY_ALPHA]);
};
