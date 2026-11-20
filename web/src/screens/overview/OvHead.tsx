/**
 * A section head on the overview: the register's mono label above a sentence-case heading,
 * with a short muted line beside it. The line sits outside the heading, so the section's
 * name is the heading alone.
 */
import type { ReactNode } from "react";

export function OvHead({ label, id, title, children }: { label: string; id: string; title: string; children?: ReactNode }) {
  return (
    <div className="section-head ov-head">
      <span className="mono-label" aria-hidden="true">
        {label}
      </span>
      <div className="ov-head-row">
        <h2 id={id}>{title}</h2>
        {children != null && <span className="ov-head-meta">{children}</span>}
      </div>
    </div>
  );
}
