/**
 * Paper building blocks as components, for screens that would rather not spell out the
 * classes in components.css. Each renders plain semantic markup; the words and figures
 * are the caller's.
 *
 * - <Lead label figure caption foot>: the one contrast card per screen.
 * - <Tiles count> with <Tile label figure note foot>: two (or 3, 4) figure tiles per row.
 * - <SectionHead label title count>: a mono register label above a sentence-case heading.
 * - <Records> with <Record label>: facts, label left and value right.
 * - <Track value max tone today>: the 6px ageing / SLA track.
 * - <Shimmer width height> and <ProgressLine label>: loading.
 */
import type { CSSProperties, ReactNode } from "react";

export function Lead({
  label,
  figure,
  caption,
  foot,
  className = "",
  figureTestId,
  "aria-label": ariaLabel,
}: {
  label: ReactNode;
  figure: ReactNode;
  caption?: ReactNode;
  foot?: ReactNode;
  className?: string;
  figureTestId?: string;
  "aria-label"?: string;
}) {
  return (
    <section className={`lead ${className}`.trim()} aria-label={ariaLabel}>
      <div className="lead-label">{label}</div>
      <div className="lead-figure" data-testid={figureTestId}>
        {figure}
      </div>
      {caption != null && <div className="lead-caption">{caption}</div>}
      {foot != null && <div className="lead-foot">{foot}</div>}
    </section>
  );
}

export function Tiles({ count = 2, children, className = "" }: { count?: 2 | 3 | 4; children: ReactNode; className?: string }) {
  const cols = count === 2 ? "" : ` tiles-${count}`;
  return <div className={`tiles${cols} ${className}`.trim()}>{children}</div>;
}

export function Tile({
  label,
  figure,
  note,
  foot,
  long = false,
  className = "",
}: {
  label: ReactNode;
  figure: ReactNode;
  note?: ReactNode;
  foot?: ReactNode;
  /** A long amount: the figure shrinks to 16px rather than wrap. */
  long?: boolean;
  className?: string;
}) {
  return (
    <div className={`tile ${className}`.trim()}>
      <div className="tile-label">{label}</div>
      <div className={`tile-figure${long ? " long" : ""}`}>{figure}</div>
      {note != null && <div className="tile-note">{note}</div>}
      {foot != null && <div className="tile-foot">{foot}</div>}
    </div>
  );
}

export function SectionHead({
  label,
  title,
  count,
  id,
  level = 2,
}: {
  /** The register's mono label (OPEN BREAKS), shown above the heading. */
  label?: string;
  title: ReactNode;
  count?: ReactNode;
  id?: string;
  level?: 2 | 3;
}) {
  const H = level === 2 ? "h2" : "h3";
  return (
    <div className="section-head">
      {label && (
        <span className="mono-label" aria-hidden="true">
          {label}
        </span>
      )}
      <H id={id}>
        {title}
        {count != null && <span className="section-count">{count}</span>}
      </H>
    </div>
  );
}

export function Records({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <dl className={`records ${className}`.trim()}>{children}</dl>;
}

export function Record({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="record">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * A 6px track filling with `value` out of `max`: grey inside SLA, muted red past it, green
 * once resolved. Decorative (the figure and its word say it), so hidden from assistive tech.
 * `today` places the single accent tick (0 to 1 along the track).
 */
export function Track({
  value,
  max,
  tone = "ok",
  today,
}: {
  value: number;
  max: number;
  tone?: "ok" | "late" | "done";
  today?: number;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(1, value / max)) * 100 : 0;
  return (
    <span className="track" aria-hidden="true">
      <span className={`track-fill${tone === "ok" ? "" : ` ${tone}`}`} style={{ width: `${pct}%` }} />
      {today != null && <span className="track-today" style={{ left: `${Math.max(0, Math.min(1, today)) * 100}%` }} />}
    </span>
  );
}

export function Shimmer({ width = "100%", height = 14, className = "" }: { width?: CSSProperties["width"]; height?: number; className?: string }) {
  return <span className={`shimmer ${className}`.trim()} style={{ width, height }} aria-hidden="true" />;
}

/** The 3px gradient line sliding across the top, with its sentence for screen readers. */
export function ProgressLine({ label = "Loading" }: { label?: string }) {
  return (
    <div className="progress-line" role="progressbar" aria-label={label}>
      <span className="sr-only">{label}</span>
    </div>
  );
}
