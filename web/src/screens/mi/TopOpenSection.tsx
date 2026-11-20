/**
 * The five open cases with the largest NAV impact, whichever way it runs. Each case id
 * opens the case in the workbench.
 */
import type { MiTopCase } from "../../api/types";
import { StatusLabel } from "../../components/Labels";
import { bp, count, money } from "../../format";
import { FLAGS, causeLabel } from "../../vocabulary";
import { CaseLink, securityText } from "../overview/caseLinks";
import { SectionHead } from "../../components/Paper";

function Flags({ c }: { c: MiTopCase }) {
  const flags: string[] = [];
  if (c.material) flags.push(FLAGS.material);
  if (c.escalated) flags.push(FLAGS.escalated);
  if (c.sla_breached) flags.push(FLAGS.sla);
  if (!flags.length) return null;
  return (
    <span className="mi-flags">
      {flags.map((f) => (
        <span key={f} className="tag">
          {f}
        </span>
      ))}
    </span>
  );
}

export function TopOpenSection({ cases, currency }: { cases: MiTopCase[]; currency: string }) {
  return (
    <section className="mi-block" aria-labelledby="mi-h-top">
      <SectionHead label="By NAV impact" title="Largest open breaks" id="mi-h-top" />
      <p className="mi-sub">top five by NAV impact, gains and losses alike</p>
      {cases.length === 0 ? (
        <p className="card empty-state">No case is open.</p>
      ) : (
        <div className="card mi-card table-wrap">
          <table className="data-table">
            <caption className="sr-only">
              The five open cases with the largest absolute NAV impact, largest first
            </caption>
            <thead>
              <tr>
                <th scope="col">Case</th>
                <th scope="col">Cause</th>
                <th scope="col" className="num">
                  <span className="sr-only">NAV impact, </span>bp
                </th>
                <th scope="col" className="num">
                  <span className="sr-only">NAV impact, </span>
                  {currency}
                </th>
                <th scope="col" className="num">
                  Age<span className="sr-only">, business days</span>
                </th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.case_id}>
                  <td>
                    <span className="mi-case-cell">
                      <CaseLink caseId={c.case_id} />
                      <span className="faint">{securityText(c)}</span>
                    </span>
                  </td>
                  <td>
                    <span className="mi-cause-cell">
                      {causeLabel(c.cause)}
                      <Flags c={c} />
                    </span>
                  </td>
                  <td className="num">{bp(c.nav_impact_bp)}</td>
                  <td className="num">{money(c.nav_impact, { signed: true })}</td>
                  <td className="num">{count(c.age_days)}</td>
                  <td>
                    <StatusLabel status={c.status} />
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
