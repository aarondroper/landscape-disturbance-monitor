export const MAP_VIEW_MODES = ["compare", "disturbance", "recovery"] as const;
export type MapViewMode = (typeof MAP_VIEW_MODES)[number];

export const DEFAULT_MAP_MODE: MapViewMode = "compare";
export const DEFAULT_RECOVERY_YEAR = 2026;
