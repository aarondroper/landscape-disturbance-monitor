import { DISTURBANCE_SOURCE_ID } from "./mapLayers";

export interface DisturbanceFeatureStateMap {
  setFeatureState: (feature: { source: string; id: string }, state: Record<string, boolean>) => void;
  getSource: (source: string) => unknown;
  isStyleLoaded: () => boolean | void;
  isRemoved?: () => boolean;
}

type MirroredMap = DisturbanceFeatureStateMap;
export type MirroredFeatureState = "hover" | "selected";

export function canApplyDisturbanceFeatureState(map: DisturbanceFeatureStateMap): boolean {
  return !map.isRemoved?.() && Boolean(map.isStyleLoaded()) && Boolean(map.getSource(DISTURBANCE_SOURCE_ID));
}

export function setDisturbanceFeatureState(
  map: DisturbanceFeatureStateMap,
  id: string,
  state: MirroredFeatureState,
  value: boolean,
): void {
  if (!canApplyDisturbanceFeatureState(map)) return;
  map.setFeatureState({ source: DISTURBANCE_SOURCE_ID, id }, { [state]: value });
}

export function setMirroredFeatureState(
  maps: readonly MirroredMap[],
  id: string,
  state: MirroredFeatureState,
  value: boolean,
): void {
  for (const map of maps) setDisturbanceFeatureState(map, id, state, value);
}

export function replaceMirroredFeatureState(
  maps: readonly MirroredMap[],
  previousId: string | undefined,
  nextId: string | undefined,
  state: MirroredFeatureState,
): void {
  if (previousId && previousId !== nextId) setMirroredFeatureState(maps, previousId, state, false);
  if (nextId) setMirroredFeatureState(maps, nextId, state, true);
}
