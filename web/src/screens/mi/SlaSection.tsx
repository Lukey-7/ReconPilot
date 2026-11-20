/**
 * SLA breaches: every case that has been open longer than its SLA, up to the day. Those
 * still open come first (they need someone), then the longest open; a breach that has
 * since cleared says when.
 */
import type { MiSlaCase } from "../../api/types";
import { Icon } from "../../components/Icon";
import { StatusLabel } from "../../components/Labels";
import { count, dayLabel } from "../../format";
import { FLAGS, causeLabel } from "../../vocabulary";
import { CaseLink, securityText } from "../overview/caseLinks";
import { SectionHead } from "../../components/Paper";

export function SlaSection({ cases }: { cases: MiSlaCase[] }) {
  const open = cases.filter((c) => !c.cleared_on).length;
  return (
    <section className="mi-block" aria-labelledby="mi-h-sla">
      <SectionHead label="Over SLA" title="SLA breaches" id="mi-h-sla" />
      <p className="mi-sub">
        {cases.length ? `${count(open)} still open, ${count(cases.length - open)} since cleared` : "none so far"}
      </p>
      {cases.length === 0 ? (
        <p className="card empty-state">No case has been open longer than its SLA.</p>
      ) : (
        <div className="card mi-card table-wrap">
          <table className="data-table">
            <caption className="sr-only">Cases open longer than their SLA, open ones first</caption>
            <thead>
              <tr>
                <th scope="col">Case</th>
                <th scope="col">Cause</th>
                <th scope="col" className="num">
                  Open<span className="sr-only">, business days</span>
                </th>
                <th scope="col" className="num">
                  SLA<span className="sr-only">, business days</span>
                </th>
                <th scope="col">Now</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.case_id}>
                  <td>
                    <span className="mi-case-cell">
                      {c.cleared_on ? <span className="mi-case-id">{c.case_id}</span> : <CaseLink caseId={c.case_id} />}
                      <span className="faint">{securityText(c)}</span>
                    </span>
                  </td>
                  <td>
                    <span className="mi-cause-cell">
                      {causeLabel(c.cause)}
                      {c.material && <span className="tag">{FLAGS.material}</span>}
                    </span>
                  </td>
                  <td className="num">{count(c.age_days)}</td>
                  <td className="num">{count(c.sla_days)}</td>
                  <td>
                    {c.cleared_on ? (
                      <span className="mi-now">
                        <StatusLabel status="CLEARED" />
                        <span className="faint">{dayLabel(c.cleared_on)}</span>
                      </span>
                    ) : (
                      <span className="mi-now">
                        <span className="tag signal">
                          <Icon name="clock" />
                          {FLAGS.sla}
                        </span>
                        <StatusLabel status={c.status} />
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
