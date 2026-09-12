export type MethodologyPanelAction =
  | { type: "open" }
  | { type: "close" }
  | { type: "keydown"; key: string };

export function methodologyPanelReducer(isOpen: boolean, action: MethodologyPanelAction): boolean {
  if (action.type === "open") return true;
  if (action.type === "close") return false;
  return action.key === "Escape" ? false : isOpen;
}
