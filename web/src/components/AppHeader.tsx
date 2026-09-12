import type { SummaryData } from "../data/types";

interface AppHeaderProps {
  summary?: SummaryData;
  summaryError?: string;
}

export function AppHeader({ summary, summaryError }: AppHeaderProps) {
  const projectSummary = summary
    ? `${summary.project.disturbance_object_count.toLocaleString("en-US")} detected disturbance areas · ${summary.project.total_analytical_disturbance_area_ha.toLocaleString("en-US")} ha`
    : summaryError
      ? "Project summary unavailable"
      : "Loading project summary…";

  return (
    <header className="app-header">
      <div className="wordmark">Landscape Disturbance Monitor</div>
      <div className="context-line">Hälsingland, Sweden · 2017–2026</div>
      <div className="descriptor">Sentinel-2 disturbance &amp; spectral recovery</div>
      <div className="project-summary">{projectSummary}</div>
    </header>
  );
}
