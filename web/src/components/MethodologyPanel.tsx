import { useEffect, useRef } from "react";
import { methodologyPanelReducer } from "./methodologyPanelState";
import { methodologySections, SOURCE_ATTRIBUTION } from "./methodologyContent";

interface MethodologyPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export function MethodologyPanel({ isOpen, onClose }: MethodologyPanelProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (methodologyPanelReducer(true, { type: "keydown", key: event.key }) === false) onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="methodology-overlay" onMouseDown={onClose}>
      <aside
        className="methodology-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="methodology-title"
        aria-describedby="methodology-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="methodology-panel__header">
          <div>
            <span className="panel-kicker">Landscape Disturbance Monitor</span>
            <h2 id="methodology-title">Methodology</h2>
          </div>
          <button ref={closeButtonRef} className="methodology-panel__close" type="button" aria-label="Close methodology panel" onClick={onClose}>
            <span aria-hidden="true">×</span>
          </button>
        </div>
        <p id="methodology-description" className="methodology-intro">A concise guide to the imagery, spectral measures, and coverage flags used in this view.</p>
        <div className="methodology-content">
          {methodologySections.map((section) => (
            <section key={section.id} className="methodology-section" aria-labelledby={`methodology-${section.id}`}>
              <h3 id={`methodology-${section.id}`}>{section.title}</h3>
              {section.paragraphs?.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
              {section.formula && <p className="methodology-formula" aria-label={section.formula}>{section.formula}</p>}
              {section.definitions && <dl className="methodology-definitions">{section.definitions.map((definition) => <div key={definition.label}><dt>{definition.label}</dt><dd>{definition.description}</dd></div>)}</dl>}
              {section.bullets && <ul>{section.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}</ul>}
            </section>
          ))}
        </div>
        <footer className="methodology-source">{SOURCE_ATTRIBUTION}</footer>
      </aside>
    </div>
  );
}
