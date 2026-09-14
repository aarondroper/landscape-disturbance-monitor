import { describe, expect, it } from "vitest";
import {
  canApplyDisturbanceFeatureState,
  replaceMirroredFeatureState,
  setDisturbanceFeatureState,
  setMirroredFeatureState,
} from "./interactionState";
import { cleanupComparisonResources } from "./comparisonLifecycle";

function fakeMap() {
  const calls: Array<{ id: string; state: Record<string, boolean> }> = [];
  let styleLoaded = true;
  let sourceReady = true;
  const map = {
    calls,
    getSource: () => sourceReady ? {} : undefined,
    isStyleLoaded: () => styleLoaded,
    setFeatureState: ({ id }: { id: string }, state: Record<string, boolean>) => calls.push({ id, state }),
  };
  return {
    ...map,
    setStyleLoaded: (value: boolean) => { styleLoaded = value; },
    setSourceReady: (value: boolean) => { sourceReady = value; },
  };
}

describe("mirrored disturbance interaction state", () => {
  it("mirrors hover state to both maps", () => {
    const before = fakeMap();
    const after = fakeMap();
    setMirroredFeatureState([before, after], new Set([before, after]), "disturbance-001", "hover", true);
    expect(before.calls).toEqual([{ id: "disturbance-001", state: { hover: true } }]);
    expect(after.calls).toEqual([{ id: "disturbance-001", state: { hover: true } }]);
  });

  it("mirrors hover clearing without touching the shared selection", () => {
    const before = fakeMap();
    const after = fakeMap();
    setMirroredFeatureState([before, after], new Set([before, after]), "disturbance-001", "hover", false);
    expect(before.calls).toEqual([{ id: "disturbance-001", state: { hover: false } }]);
    expect(after.calls).toEqual(before.calls);
  });

  it("replaces one selected feature on both maps", () => {
    const before = fakeMap();
    const after = fakeMap();
    replaceMirroredFeatureState([before, after], new Set([before, after]), "disturbance-001", "disturbance-002", "selected");
    expect(before.calls).toEqual([
      { id: "disturbance-001", state: { selected: false } },
      { id: "disturbance-002", state: { selected: true } },
    ]);
    expect(after.calls).toEqual(before.calls);
  });

  it("has one selection state rather than independent map selections", () => {
    const before = fakeMap();
    const after = fakeMap();
    const readyMaps = new Set([before, after]);
    replaceMirroredFeatureState([before, after], readyMaps, undefined, "disturbance-001", "selected");
    replaceMirroredFeatureState([before, after], readyMaps, "disturbance-001", undefined, "selected");
    expect(before.calls).toEqual([
      { id: "disturbance-001", state: { selected: true } },
      { id: "disturbance-001", state: { selected: false } },
    ]);
    expect(after.calls).toEqual(before.calls);
  });

  it("requires style and disturbance source readiness before feature state", () => {
    const map = fakeMap();
    map.setStyleLoaded(false);
    expect(canApplyDisturbanceFeatureState(map, true)).toBe(false);
    setDisturbanceFeatureState(map, true, "disturbance-001", "selected", true);
    expect(map.calls).toEqual([]);

    map.setStyleLoaded(true);
    map.setSourceReady(false);
    expect(canApplyDisturbanceFeatureState(map, true)).toBe(false);
    setDisturbanceFeatureState(map, true, "disturbance-001", "selected", true);
    expect(map.calls).toEqual([]);

    map.setSourceReady(true);
    expect(canApplyDisturbanceFeatureState(map, true)).toBe(true);
    setDisturbanceFeatureState(map, true, "disturbance-001", "selected", true);
    expect(map.calls).toEqual([{ id: "disturbance-001", state: { selected: true } }]);
  });

  it("updates only independently ready Compare maps and applies current selection to the second map later", () => {
    const before = fakeMap();
    const after = fakeMap();
    const readyMaps = new Set([before]);
    setMirroredFeatureState([before, after], readyMaps, "disturbance-002", "selected", true);
    expect(before.calls).toEqual([{ id: "disturbance-002", state: { selected: true } }]);
    expect(after.calls).toEqual([]);

    readyMaps.add(after);
    setMirroredFeatureState([after], readyMaps, "disturbance-002", "selected", true);
    expect(after.calls).toEqual([{ id: "disturbance-002", state: { selected: true } }]);
  });

  it("does not restore an old selection when the current selection changes before readiness", () => {
    const map = fakeMap();
    const readyMaps = new Set<typeof map>();
    replaceMirroredFeatureState([map], readyMaps, "disturbance-001", "disturbance-002", "selected");
    expect(map.calls).toEqual([]);
    readyMaps.add(map);
    setMirroredFeatureState([map], readyMaps, "disturbance-002", "selected", true);
    expect(map.calls).toEqual([{ id: "disturbance-002", state: { selected: true } }]);
  });

  it("cleans up listeners, comparison control, and both map instances", () => {
    const events: string[] = [];
    cleanupComparisonResources(
      { remove: () => events.push("compare") },
      [{ remove: () => events.push("before") }, { remove: () => events.push("after") }],
      [() => events.push("listener")],
    );
    expect(events).toEqual(["listener", "compare", "before", "after"]);
  });
});
