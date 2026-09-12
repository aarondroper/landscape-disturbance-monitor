import type { RefObject } from "react";
import type { SummaryData } from "../data/types";
import { MAP_VIEW_MODES, type MapViewMode } from "../map/viewMode";

interface AppHeaderProps {
  summary?: SummaryData;
  summaryError?: string;
  mode: MapViewMode;
  onModeChange: (mode: MapViewMode) => void;
  methodologyButtonRef: RefObject<HTMLButtonElement | null>;
  onMethodology: () => void;
}

export function AppHeader({ summary, summaryError, mode, onModeChange, methodologyButtonRef, onMethodology }: AppHeaderProps) {
  const projectSummary = summary
    ? `${summary.project.disturbance_object_count.toLocaleString("en-US")} detected disturbance areas · ${summary.project.total_analytical_disturbance_area_ha.toLocaleString("en-US")} ha`
    : summaryError
      ? "Project summary unavailable"
      : "Loading project summary…";

  return (
    <header className="app-header">
      <div className="wordmark">Landscape Disturbance Monitor</div>
      <div className="context-line">Hälsingland, Sweden · 2017–2026</div>
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
    </header>
  );
}
