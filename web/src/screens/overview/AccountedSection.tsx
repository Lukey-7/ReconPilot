/**
 * "Every break accounted for" (the Ledger's day account): every break the run found, where
 * it sits, and how far the open cases have got, as records (label left, figure right). The
 * server guarantees the sums (found = in a case + not in a case; open = decided + pending);
 * this section only shows them.
 */
import type { Overview } from "../../api/types";
import { Icon } from "../../components/Icon";
import { count, plural } from "../../format";
import { OvHead } from "./OvHead";

type Accounted = NonNullable<Overview["accounted"]>;

function Row({ label, value, kind = "" }: { label: string; value: number; kind?: "sub" | "total" | "" }) {
  return (
    <div className={`record ov-acc-row ${kind}`.trim()}>
      <dt>{label}</dt>
      <dd className="fig">{count(value)}</dd>
    </div>
  );
}

/** The plain-words line under the account when every break is in a case. */
function placedSentence(a: Accounted): string {
  const placed =
    a.breaks_found === 0
      ? "The run found no breaks"
      : a.breaks_found === 1
        ? "The one break sits in a case"
        : `All ${count(a.breaks_found)} breaks sit in a case`;
  let cases: string;
  if (a.open_cases === 0) cases = "no case is open";
  else if (a.pending === 0) cases = "every open case is decided";
  else cases = `${plural(a.pending, "case")} still ${a.pending === 1 ? "waits" : "wait"} for a decision`;
  return `${placed}; ${cases}.`;
}

export function AccountedSection({ accounted, run }: { accounted: Accounted; run: Overview["run"] }) {
  const unplaced = accounted.breaks_not_in_case;
  return (
    <section className="ov-accounted" aria-labelledby="ov-h-accounted">
      <OvHead label="Break account" id="ov-h-accounted" title="Every break accounted for" />
      <div className="card ov-acc-card">
        <dl className="records ov-acc">
          <Row label="Breaks found by this run" value={accounted.breaks_found} />
          <Row label="Held in a case" value={accounted.breaks_in_cases} kind="sub" />
          <Row label="Not in any case" value={unplaced} kind="sub" />
          <Row label="Open cases" value={accounted.open_cases} />
          <Row label="Approved" value={accounted.approved} kind="sub" />
          <Row label="Reclassified" value={accounted.reclassified} kind="sub" />
          <Row label="Rejected" value={accounted.rejected} kind="sub" />
          <Row label="Pending a decision" value={accounted.pending} kind="sub" />
          <Row label="Decided or pending" value={accounted.decided + accounted.pending} kind="total" />
        </dl>
        <div className="ov-acc-notes">
          {unplaced > 0 ? (
            <p className="ov-note ov-alert">
              <Icon name="warn" />
              <span>
                {plural(unplaced, "break")} {unplaced === 1 ? "is" : "are"} not in any case. Every break must be held in a
                case before sign-off.
              </span>
            </p>
          ) : (
            <p className="ov-note muted">{placedSentence(accounted)}</p>
          )}
          {run && (
            <p className="ov-note muted">
              This run: {plural(run.matches, "match", "matches")}, {plural(run.new_cases, "new case")},{" "}
              {plural(run.carried_cases, "case")} carried from earlier days.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
