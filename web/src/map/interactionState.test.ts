import { describe, expect, it } from "vitest";
import { replaceMirroredFeatureState, setMirroredFeatureState } from "./interactionState";
import { cleanupComparisonResources } from "./comparisonLifecycle";

function fakeMap() {
  const calls: Array<{ id: string; state: Record<string, boolean> }> = [];
  return {
    calls,
    setFeatureState: ({ id }: { id: string }, state: Record<string, boolean>) => calls.push({ id, state }),
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
