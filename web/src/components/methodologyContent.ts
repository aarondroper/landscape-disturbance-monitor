export interface MethodologySection {
  id: string;
  title: string;
  paragraphs?: readonly string[];
  bullets?: readonly string[];
  formula?: string;
  definitions?: readonly { label: string; description: string }[];
}

export const RECOVERY_FORMULA = "recovery_y = (NBR_y − NBR_2018) / (NBR_2017 − NBR_2018)";
export const SOURCE_ATTRIBUTION = "Sentinel-2 L2A · Copernicus · via Element 84 Earth Search";

export const methodologySections: readonly MethodologySection[] = [
  {
    id: "what-this-shows",
    title: "What this shows",
    paragraphs: [
      "This application uses Sentinel-2 imagery to identify major vegetation disturbance between 2017 and 2018 and follow subsequent spectral change through 2026.",
      "It examines a fixed 2018 disturbance landscape in Hälsingland using annual Sentinel-2 observations.",
    ],
  },
  {
    id: "compare",
    title: "Compare",
    paragraphs: [
      "August 2017 and August 2018 natural-color Sentinel-2 composites use the same fixed display treatment. Drag the divider for a visual before/after comparison.",
    ],
  },
  {
    id: "disturbance",
    title: "Disturbance",
    paragraphs: [
      "dNBR = NBR2017 − NBR2018. Detected objects required NBR2017 > 0.30, dNBR ≥ 0.30, and connected retained area ≥ 5 ha.",
      "This is a project-specific spectral-disturbance rule, not an authoritative wildfire perimeter or burn-severity classification.",
    ],
  },
  {
    id: "recovery",
    title: "Recovery",
    paragraphs: [
      "Spectral recovery is calculated for each year using the normalized change formula:",
      "Spectral recovery is not the same as ecological recovery.",
    ],
    formula: RECOVERY_FORMULA,
    definitions: [
      { label: "0", description: "≈ 2018 post-disturbance NBR state" },
      { label: "1", description: "≈ 2017 NBR baseline" },
      { label: "> 1", description: "NBR exceeds the 2017 spectral baseline" },
      { label: "< 0", description: "NBR is below the 2018 state" },
    ],
  },
  {
    id: "coverage",
    title: "Coverage",
    paragraphs: [
      "Coverage describes the share of valid pixels in each disturbance object for that annual observation.",
    ],
    bullets: [
      "Good: ≥95% valid object pixels",
      "Partial: ≥80% and <95%",
      "Poor: <80%",
      "Missing annual pixels are not interpolated or filled. Poor observations remain visible but are de-emphasized.",
    ],
  },
  {
    id: "data",
    title: "Data",
    bullets: [
      "Copernicus Sentinel-2 Level-2A",
      "Accessed through Element 84 Earth Search",
      "Annual August composites",
      "Analytical grid: 20 m",
      "Natural-color presentation imagery: 10 m",
      "2017–2026 annual analysis",
    ],
  },
  {
    id: "limitations",
    title: "Limitations",
    bullets: [
      "Later-year valid coverage varies by disturbance object.",
      "Spectral indices are proxies, not direct ecological measurements.",
      "No causal attribution is made for later spectral changes.",
      "Detected objects are project-derived rather than an official event perimeter.",
      "Missing observations remain missing.",
    ],
  },
];
