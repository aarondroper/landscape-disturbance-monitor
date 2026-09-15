import type { RefObject } from "react";
import type { SummaryData } from "../data/types";
import { MAP_VIEW_MODES, type MapViewMode } from "../map/viewMode";

interface AppHeaderProps {
  summary?: SummaryData;
  summaryError?: string;
  mode: MapViewMode;
  onModeChange: (mode: MapViewMode) => void;
  disturbanceBoundariesVisible: boolean;
  onDisturbanceBoundariesVisibleChange: (visible: boolean) => void;
  methodologyButtonRef: RefObject<HTMLButtonElement | null>;
  onMethodology: () => void;
}

export function AppHeader({ summary, summaryError, mode, onModeChange, disturbanceBoundariesVisible, onDisturbanceBoundariesVisibleChange, methodologyButtonRef, onMethodology }: AppHeaderProps) {
  const projectSummary = summary
    ? `${summary.project.disturbance_object_count.toLocaleString("en-US")} detected disturbance areas · ${summary.project.total_analytical_disturbance_area_ha.toLocaleString("en-US")} ha`
    : summaryError
      ? "Project summary unavailable"
      : "Loading project summary…";

  return (
    <header className="app-sidebar" aria-label="Project and map controls">
      <div className="brand-lockup">
        <div className="app-logo-slot" aria-hidden="true">
          <img className="app-logo" src="/app-logo.svg" alt="" />
        </div>
        <div className="app-title-block">
          <div className="wordmark">Landscape Disturbance Monitor</div>
          <div className="context-line">Hälsingland, Sweden · 2017–2026</div>
        </div>
      </div>
      <div className="header-row">
        <div className="descriptor">Sentinel-2 disturbance &amp; spectral recovery</div>
        <button ref={methodologyButtonRef} className="methodology-trigger" type="button" onClick={onMethodology}>Methodology</button>
      </div>
      <div className="project-summary">{projectSummary}</div>
      <div className="mode-switch" role="tablist" aria-label="Map view">
        {MAP_VIEW_MODES.map((option) => (
          <button
            key={option}
            type="button"
            role="tab"
            aria-selected={mode === option}
            className={mode === option ? "mode-switch__button mode-switch__button--active" : "mode-switch__button"}
            onClick={() => onModeChange(option)}
          >
            {option === "compare" ? "Compare" : option === "disturbance" ? "Disturbance" : "Recovery"}
          </button>
        ))}
      </div>
      <label className="boundary-toggle">
        <span className="boundary-toggle__label">Disturbance boundaries</span>
        <span className="boundary-toggle__control">
          <input
            className="boundary-toggle__input"
            type="checkbox"
            checked={disturbanceBoundariesVisible}
            onChange={(event) => onDisturbanceBoundariesVisibleChange(event.target.checked)}
            aria-label="Disturbance boundaries"
          />
          <span className="boundary-toggle__track" aria-hidden="true"><span className="boundary-toggle__thumb" /></span>
        </span>
        <span className="boundary-toggle__state" aria-hidden="true">{disturbanceBoundariesVisible ? "ON" : "OFF"}</span>
      </label>
    </header>
  );
}
