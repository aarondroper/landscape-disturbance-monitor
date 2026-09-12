interface Removable {
  remove: () => void;
}

export function cleanupComparisonResources(
  compare: Removable | undefined,
  maps: readonly Removable[],
  listeners: readonly (() => void)[],
): void {
  for (const cleanup of listeners) cleanup();
  compare?.remove();
  for (const map of maps) map.remove();
}
