/**
 * The day's release status first, with its reasons in plain words, then the release
 * checks behind an expander. The status is the server's (`overview.release`, computed by
 * the same functions as `GET .../release`), so it always agrees with the NAV strip.
 */
import type { Check, Overview } from "../../api/types";
import { CheckLabel, ReleaseBadge, releaseState } from "../../components/Labels";
import { plural, timestamp } from "../../format";
import { checkLabel, releaseReasonLabel } from "../../vocabulary";
import { CaseLink } from "./caseLinks";

/** How many case links a reason shows before the rest go behind "Show all". */
export const REASON_CASES_SHOWN = 6;

function CaseIds({ ids }: { ids: string[] }) {
  if (!ids.length) return null;
  const shown = ids.slice(0, REASON_CASES_SHOWN);
  const rest = ids.slice(REASON_CASES_SHOWN);
  return (
    <div className="ov-reason-cases">
      <ul aria-label="Cases">
        {shown.map((id) => (
          <li key={id}>
            <CaseLink caseId={id} />
          </li>
        ))}
      </ul>
      {rest.length > 0 && (
        <details className="ov-more">
          <summary>Show all {plural(ids.length, "case")}</summary>
          <ul aria-label="More cases">
            {rest.map((id) => (
              <li key={id}>
                <CaseLink caseId={id} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** "4 pass, 1 warning, 1 fail": the checks in one line, worded by the vocabulary. */
export function checksSummary(checks: Check[]): string {
  const order = ["PASS", "WARN", "FAIL"];
  const counts = new Map<string, number>();
  for (const c of checks) counts.set(c.status, (counts.get(c.status) ?? 0) + 1);
  const known = order.filter((s) => counts.has(s));
  const other = [...counts.keys()].filter((s) => !order.includes(s));
  return [...known, ...other]
    .map((s) => `${counts.get(s) ?? 0} ${checkLabel(s).toLowerCase()}`)
    .join(", ");
}

function Checks({ checks }: { checks: Check[] }) {
  if (!checks.length) return null;
  return (
    <details className="ov-checks">
      <summary>
        Release checks <span className="faint">({checksSummary(checks)})</span>
      </summary>
      <table className="data-table ov-checks-table">
        <caption className="sr-only">Release checks</caption>
        <thead>
          <tr>
            <th scope="col">Result</th>
            <th scope="col">Check</th>
            <th scope="col">Detail</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c) => (
            <tr key={c.name}>
              <td>
                <CheckLabel status={c.status} />
              </td>
              <td>{c.name}</td>
              <td className="muted">{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

export function ReleaseSection({ overview }: { overview: Overview }) {
  const signedOff = overview.day_status === "signed_off" || !!overview.signed_off_at;
  const state = releaseState(overview.release, signedOff);
  const reasons = overview.release.reasons;

  let headline: string;
  if (signedOff) {
    headline = `Signed off by ${overview.signed_off_by ?? "an approver"}, ${timestamp(overview.signed_off_at)}. The day is locked.`;
  } else if (state === "ready") {
    headline = "Every release condition is met. An approver can sign off the NAV.";
  } else if (reasons.length === 1) {
    headline = "One thing stands between this day and sign-off.";
  } else {
    headline = `${reasons.length} things stand between this day and sign-off.`;
  }

  return (
    <section className="ov-block ov-release" aria-labelledby="ov-h-release" data-state={state}>
      <h2 id="ov-h-release">Release status</h2>
      <div className="ov-release-state" aria-live="polite">
        <ReleaseBadge state={state} />
        <p className="ov-headline">{headline}</p>
      </div>
      {!signedOff && reasons.length > 0 && (
        <ol className="ov-reasons" aria-label="Why release is blocked">
          {reasons.map((r, i) => (
            <li key={`${r.code}-${i}`} data-reason={r.code}>
              <span className="ov-reason-name">{releaseReasonLabel(r.code)}</span>
              <span className="ov-reason-text">{r.message}</span>
              <CaseIds ids={r.case_ids} />
            </li>
          ))}
        </ol>
      )}
      <Checks checks={overview.checks} />
    </section>
  );
}
