import { DISTURBANCE_SOURCE_ID } from "./mapLayers";

export interface DisturbanceFeatureStateMap {
  setFeatureState: (feature: { source: string; id: string }, state: Record<string, boolean>) => void;
  getSource: (source: string) => unknown;
  isStyleLoaded: () => boolean | void;
}

type MirroredMap = {
  setFeatureState: DisturbanceFeatureStateMap["setFeatureState"];
  getSource: DisturbanceFeatureStateMap["getSource"];
  isStyleLoaded: DisturbanceFeatureStateMap["isStyleLoaded"];
};
export type MirroredFeatureState = "hover" | "selected";

export function canApplyDisturbanceFeatureState(map: DisturbanceFeatureStateMap, sourceReady: boolean): boolean {
  return sourceReady && Boolean(map.isStyleLoaded()) && Boolean(map.getSource(DISTURBANCE_SOURCE_ID));
}

export function setDisturbanceFeatureState(
  map: DisturbanceFeatureStateMap,
  sourceReady: boolean,
  id: string,
  state: MirroredFeatureState,
  value: boolean,
): void {
  if (!canApplyDisturbanceFeatureState(map, sourceReady)) return;
  map.setFeatureState({ source: DISTURBANCE_SOURCE_ID, id }, { [state]: value });
}

export function setMirroredFeatureState(
  maps: readonly MirroredMap[],
  readyMaps: ReadonlySet<MirroredMap>,
  id: string,
  state: MirroredFeatureState,
  value: boolean,
): void {
  for (const map of maps) {
    if (readyMaps.has(map)) setDisturbanceFeatureState(map, true, id, state, value);
  }
}

export function replaceMirroredFeatureState(
  maps: readonly MirroredMap[],
  readyMaps: ReadonlySet<MirroredMap>,
  previousId: string | undefined,
  nextId: string | undefined,
  state: MirroredFeatureState,
): void {
  if (previousId && previousId !== nextId) setMirroredFeatureState(maps, readyMaps, previousId, state, false);
  if (nextId) setMirroredFeatureState(maps, readyMaps, nextId, state, true);
}
