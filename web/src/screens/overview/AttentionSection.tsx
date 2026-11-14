/**
 * SLA breaches and escalations: the open cases that have waited too long or crossed a
 * threshold. An escalation's reason is what was recorded when the case was escalated, so
 * it is labelled "at escalation" and never passed off as today's impact.
 */
import type { ReactNode } from "react";

import type { OverviewCase } from "../../api/types";
import { Icon } from "../../components/Icon";
import { StatusLabel } from "../../components/Labels";
import { money, plural } from "../../format";
import { CaseLink, currentCause, securityText } from "./caseLinks";

function capitalise(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

function CaseLine({ c, children }: { c: OverviewCase; children: ReactNode }) {
  return (
    <li className="ov-att-item" data-case={c.case_id}>
      <div className="ov-att-top">
        <CaseLink caseId={c.case_id} />
        <span className="ov-att-sec">{securityText(c)}</span>
        <StatusLabel status={c.status} />
      </div>
      <div className="ov-att-detail muted">
        {currentCause(c)}, <span className="fig">{money(c.nav_impact, { signed: true })}</span>. {children}
      </div>
    </li>
  );
}

export function AttentionSection({ slaBreaches, escalations }: { slaBreaches: OverviewCase[]; escalations: OverviewCase[] }) {
  const nothing = slaBreaches.length === 0 && escalations.length === 0;
  return (
    <section className="ov-block ov-attention" aria-labelledby="ov-h-attention">
      <h2 id="ov-h-attention">SLA breaches and escalations</h2>
      {nothing ? (
        <p className="ov-note muted">
          <Icon name="check" /> No open case is past its SLA, and none is escalated.
        </p>
      ) : (
        <>
          <h3 className="ov-sub" id="ov-h-sla">
            Past SLA <span className="faint">{slaBreaches.length ? plural(slaBreaches.length, "case") : "none"}</span>
          </h3>
          {slaBreaches.length > 0 && (
            <ul className="ov-att-list" aria-labelledby="ov-h-sla">
              {slaBreaches.map((c) => (
                <CaseLine key={c.case_id} c={c}>
                  <span className="ov-signal">
                    <Icon name="clock" />
                    Open {plural(c.age_days, "business day")}, SLA {plural(c.sla_days, "day")}.
                  </span>
                </CaseLine>
              ))}
            </ul>
          )}
          <h3 className="ov-sub" id="ov-h-esc">
            Escalated <span className="faint">{escalations.length ? plural(escalations.length, "case") : "none"}</span>
          </h3>
          {escalations.length > 0 && (
            <ul className="ov-att-list" aria-labelledby="ov-h-esc">
              {escalations.map((c) => (
                <CaseLine key={c.case_id} c={c}>
                  <span>
                    <span className="faint">At escalation: </span>
                    {capitalise(c.escalation_reason) || "no reason recorded"}.
                  </span>
                </CaseLine>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
