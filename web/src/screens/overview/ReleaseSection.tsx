/**
 * The overview's lead card and the day's release status. The lead card carries NAV per
 * share (counting up when a day loads), the NAV in the fund's currency with the day-on-day
 * move as its caption, and the release status with its headline in plain words. Under it,
 * one card gives the reasons in plain words and the release checks behind an expander.
 * The status is the server's (`overview.release`, computed by the same functions as
 * `GET .../release`), so it always agrees with the NAV strip.
 */
import type { Check, Overview } from "../../api/types";
import { Icon } from "../../components/Icon";
import { CheckLabel, ReleaseBadge, releaseState } from "../../components/Labels";
import { money, perShare, plural, signedPercent, timestamp } from "../../format";
import { useChangeCount } from "../../motion";
import { checkLabel, releaseReasonLabel } from "../../vocabulary";
import { CaseLink } from "./caseLinks";
import { useCountUp } from "./useCountUp";

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

/** The day-on-day move of NAV per share, with its direction in words as well as the arrow. */
function Movement({ nav }: { nav: NonNullable<Overview["nav"]> }) {
  if (nav.movement == null || !nav.prior_nav_per_share) return <span>No prior NAV</span>;
  const direction = nav.movement > 0 ? "up" : nav.movement < 0 ? "down" : "flat";
  const word = { up: "Up", down: "Down", flat: "Unchanged" }[direction];
  return (
    <span className="ov-move">
      <Icon name={direction} />
      <span className="sr-only">{word} </span>
      <span className="fig">{signedPercent(nav.movement)}</span> on <span className="fig">{perShare(nav.prior_nav_per_share)}</span>
    </span>
  );
}

export function ReleaseSection({ overview }: { overview: Overview }) {
  const signedOff = overview.day_status === "signed_off" || !!overview.signed_off_at;
  const state = releaseState(overview.release, signedOff);
  const reasons = overview.release.reasons;
  const scope = `${overview.fund.code}|${overview.as_of}`;
  const changes = useChangeCount(state, scope);
  const nav = overview.nav;
  const nps = useCountUp(nav?.nav_per_share ?? null, scope);
  const currency = overview.fund.base_currency;

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

  const showReasons = !signedOff && reasons.length > 0;
  return (
    <section className="ov-release" aria-labelledby="ov-h-release" data-state={state}>
      <div className="lead ov-lead">
        <div className="ov-lead-nav">
          <div className="lead-label">NAV per share</div>
          <div className="lead-figure" data-testid="ov-nps">
            {perShare(nps)}
          </div>
          <div className="lead-caption ov-lead-caption">
            {nav ? (
              <>
                <span>
                  NAV <span className="fig ov-lead-nav-figure">{money(nav.nav)}</span> {currency}
                </span>
                <Movement nav={nav} />
              </>
            ) : (
              <span>Not run yet</span>
            )}
          </div>
        </div>
        <div className="ov-lead-release">
          <h2 id="ov-h-release" className="mono-label">
            Release status
          </h2>
          <div className="ov-release-state" aria-live="polite">
            <ReleaseBadge key={changes} state={state} changed={changes > 0} />
            <p className="ov-headline">{headline}</p>
          </div>
        </div>
      </div>
      {(showReasons || overview.checks.length > 0) && (
        <div className="card ov-reasons-card">
          {showReasons && (
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
        </div>
      )}
    </section>
  );
}
