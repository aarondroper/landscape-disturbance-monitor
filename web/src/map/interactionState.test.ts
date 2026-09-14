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
  let removed = false;
  const map = {
    calls,
    getSource: () => sourceReady ? {} : undefined,
    isStyleLoaded: () => styleLoaded,
    isRemoved: () => removed,
    setFeatureState: ({ id }: { id: string }, state: Record<string, boolean>) => calls.push({ id, state }),
  };
  return {
    ...map,
    setStyleLoaded: (value: boolean) => { styleLoaded = value; },
    setSourceReady: (value: boolean) => { sourceReady = value; },
    setRemoved: (value: boolean) => { removed = value; },
  };
}

describe("mirrored disturbance interaction state", () => {
  it("mirrors hover state to both maps", () => {
    const before = fakeMap();
    const after = fakeMap();
    setMirroredFeatureState([before, after], "disturbance-001", "hover", true);
    expect(before.calls).toEqual([{ id: "disturbance-001", state: { hover: true } }]);
    expect(after.calls).toEqual([{ id: "disturbance-001", state: { hover: true } }]);
  });

  it("mirrors hover clearing without touching the shared selection", () => {
    const before = fakeMap();
    const after = fakeMap();
    setMirroredFeatureState([before, after], "disturbance-001", "hover", false);
    expect(before.calls).toEqual([{ id: "disturbance-001", state: { hover: false } }]);
    expect(after.calls).toEqual(before.calls);
  });

  it("replaces one selected feature on both maps", () => {
    const before = fakeMap();
    const after = fakeMap();
    replaceMirroredFeatureState([before, after], "disturbance-001", "disturbance-002", "selected");
    expect(before.calls).toEqual([
      { id: "disturbance-001", state: { selected: false } },
      { id: "disturbance-002", state: { selected: true } },
    ]);
    expect(after.calls).toEqual(before.calls);
  });

  it("has one selection state rather than independent map selections", () => {
    const before = fakeMap();
    const after = fakeMap();
    replaceMirroredFeatureState([before, after], undefined, "disturbance-001", "selected");
    replaceMirroredFeatureState([before, after], "disturbance-001", undefined, "selected");
    expect(before.calls).toEqual([
      { id: "disturbance-001", state: { selected: true } },
      { id: "disturbance-001", state: { selected: false } },
    ]);
    expect(after.calls).toEqual(before.calls);
  });

  it("requires style and disturbance source readiness before feature state", () => {
    const map = fakeMap();
    map.setStyleLoaded(false);
    expect(canApplyDisturbanceFeatureState(map)).toBe(false);
    setDisturbanceFeatureState(map, "disturbance-001", "selected", true);
    expect(map.calls).toEqual([]);

    map.setStyleLoaded(true);
    map.setSourceReady(false);
    expect(canApplyDisturbanceFeatureState(map)).toBe(false);
    setDisturbanceFeatureState(map, "disturbance-001", "selected", true);
    expect(map.calls).toEqual([]);

    map.setSourceReady(true);
    expect(canApplyDisturbanceFeatureState(map)).toBe(true);
    setDisturbanceFeatureState(map, "disturbance-001", "selected", true);
    expect(map.calls).toEqual([{ id: "disturbance-001", state: { selected: true } }]);

    map.setRemoved(true);
    expect(canApplyDisturbanceFeatureState(map)).toBe(false);
    setDisturbanceFeatureState(map, "disturbance-002", "selected", true);
    expect(map.calls).toHaveLength(1);
  });

  it("updates only independently ready Compare maps and applies current selection to the second map later", () => {
    const before = fakeMap();
    const after = fakeMap();
    after.setSourceReady(false);
    setMirroredFeatureState([before, after], "disturbance-002", "selected", true);
    expect(before.calls).toEqual([{ id: "disturbance-002", state: { selected: true } }]);
    expect(after.calls).toEqual([]);

    after.setSourceReady(true);
    setMirroredFeatureState([after], "disturbance-002", "selected", true);
    expect(after.calls).toEqual([{ id: "disturbance-002", state: { selected: true } }]);
  });

  it("does not restore an old selection when the current selection changes before readiness", () => {
    const map = fakeMap();
    map.setSourceReady(false);
    replaceMirroredFeatureState([map], "disturbance-001", "disturbance-002", "selected");
    expect(map.calls).toEqual([]);
    map.setSourceReady(true);
    setMirroredFeatureState([map], "disturbance-002", "selected", true);
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
