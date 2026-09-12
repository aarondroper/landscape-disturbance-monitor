type MirroredMap = {
  setFeatureState: (feature: { source: string; id: string }, state: Record<string, boolean>) => void;
};
export type MirroredFeatureState = "hover" | "selected";

export function setMirroredFeatureState(
  maps: readonly MirroredMap[],
  id: string,
  state: MirroredFeatureState,
  value: boolean,
): void {
  for (const map of maps) {
    map.setFeatureState({ source: "disturbances", id }, { [state]: value });
  }
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
