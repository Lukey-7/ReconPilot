/**
 * Cases that cleared on this day's run: a later day's data matched them, so they leave the
 * open list. The count shows at once; the cases and why each cleared are a click away.
 */
import type { ClearedCase } from "../../api/types";
import { CauseLabel } from "../../components/Labels";
import { count, money, plural } from "../../format";
import { causeLabel } from "../../vocabulary";
import { CaseLink, securityText } from "./caseLinks";

/** Up to this many cleared cases show without opening the list. */
export const CLEARED_SHOWN_OPEN = 3;

function ClearedTable({ cases, currency }: { cases: ClearedCase[]; currency: string }) {
  return (
    <div className="table-wrap">
      <table className="data-table ov-cleared-table">
        <caption className="sr-only">Cases cleared on this day, with why each cleared</caption>
        <thead>
          <tr>
            <th scope="col">Case</th>
            <th scope="col">Resolved as</th>
            <th scope="col" className="num">
              Impact<span className="sr-only">, {currency}</span>
            </th>
            <th scope="col" className="num">
              Age<span className="sr-only">, business days</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.case_id}>
              <td>
                <span className="ov-case-cell">
                  <CaseLink caseId={c.case_id} />
                  <span className="faint ov-sec">{securityText(c)}</span>
                </span>
              </td>
              <td>
                <span className="ov-cause-cell">
                  <CauseLabel cause={c.resolved_category ?? c.final_category ?? c.category} />
                  {c.clear_reason && <span className="faint ov-why">{c.clear_reason}</span>}
                </span>
              </td>
              <td className="num">{money(c.nav_impact, { signed: true })}</td>
              <td className="num">{count(c.age_days)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ClearedSection({ cleared, currency }: { cleared: ClearedCase[]; currency: string }) {
  const causes = [...new Set(cleared.map((c) => causeLabel(c.resolved_category ?? c.final_category ?? c.category)))];
  return (
    <section className="ov-block ov-cleared" aria-labelledby="ov-h-cleared">
      <div className="ov-block-head">
        <h2 id="ov-h-cleared">Cleared today</h2>
        <span className="faint">{cleared.length ? plural(cleared.length, "case") : "none"}</span>
      </div>
      {cleared.length === 0 ? (
        <p className="ov-note muted">No case cleared on this day&rsquo;s run.</p>
      ) : cleared.length <= CLEARED_SHOWN_OPEN ? (
        <ClearedTable cases={cleared} currency={currency} />
      ) : (
        <details className="ov-more-block">
          <summary>
            Show the {plural(cleared.length, "cleared case")} <span className="faint">({causes.join(", ")})</span>
          </summary>
          <ClearedTable cases={cleared} currency={currency} />
        </details>
      )}
    </section>
  );
}
