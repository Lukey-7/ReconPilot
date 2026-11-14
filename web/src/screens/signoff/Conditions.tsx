/**
 * The release conditions (the Ledger's sign-off page): every condition the server checks,
 * met or not, in plain words. An unmet condition shows the server's own reason and the
 * cases behind it; a met one says briefly why it holds, from the day's live figures.
 * The browser never decides a condition: it is unmet exactly when the server's release
 * status (or, for four-eyes, `blocking_for_me`) names it.
 */
import type { Overview, Reason, ReleaseForMe, RoleName } from "../../api/types";
import { Icon } from "../../components/Icon";
import { plural } from "../../format";
import { releaseConditionLabel } from "../../vocabulary";
import { checksSummary } from "../overview/ReleaseSection";
import { CaseIdList } from "./CaseIdList";

type State = "met" | "unmet" | "na";

interface Condition {
  code: string;
  state: State;
  /** The server's reasons when unmet; otherwise one line saying why it holds. */
  reasons: Reason[];
  detail: string;
}

const DAY_CONDITIONS = ["PENDING_DECISIONS", "MATERIAL_NOT_APPROVED", "ESCALATED_NEEDS_APPROVER", "CHECK_FAILED"] as const;

function metDetail(code: string, overview: Overview | undefined, release: ReleaseForMe): string {
  const open = overview?.impact?.cases ?? null;
  switch (code) {
    case "PENDING_DECISIONS": {
      if (!open) return "Every open case has a decision.";
      if (!open.length) return "No case is open.";
      return open.length === 1 ? "The one open case has a decision." : `All ${plural(open.length, "open case")} have a decision.`;
    }
    case "MATERIAL_NOT_APPROVED": {
      const n = open?.filter((c) => c.material).length;
      if (n == null) return "Every material case is approved or reclassified.";
      return n ? `${plural(n, "material case")} approved or reclassified.` : "No material case is open.";
    }
    case "ESCALATED_NEEDS_APPROVER": {
      const n = open?.filter((c) => c.escalated).length;
      if (n == null) return "Every escalated case has an approver's decision.";
      return n ? `${plural(n, "escalated case")} decided by an approver.` : "No escalated case is open.";
    }
    case "CHECK_FAILED": {
      if (!release.checks.length) return "No release check failed.";
      const warn = release.checks.some((c) => c.status === "WARN");
      return `${checksSummary(release.checks)}.${warn ? " Warnings do not block release." : ""}`;
    }
    default:
      return "";
  }
}

/** The conditions for this day and this person, in the order the server checks them. */
export function conditionsFor(
  release: ReleaseForMe,
  overview: Overview | undefined,
  role: RoleName,
  signedOffBy: string | null,
): Condition[] {
  const notRun = release.reasons.filter((r) => r.code === "NOT_RUN");
  if (notRun.length) return [{ code: "NOT_RUN", state: "unmet", reasons: notRun, detail: "" }];

  const out: Condition[] = DAY_CONDITIONS.map((code) => {
    const reasons = release.reasons.filter((r) => r.code === code);
    return reasons.length
      ? { code, state: "unmet", reasons, detail: "" }
      : { code, state: "met", reasons: [], detail: metDetail(code, overview, release) };
  });

  // Any reason the vocabulary does not know yet still shows, under its own code.
  const known = new Set<string>(["NOT_RUN", "FOUR_EYES", ...DAY_CONDITIONS]);
  for (const r of release.reasons) {
    if (!known.has(r.code)) out.push({ code: r.code, state: "unmet", reasons: [r], detail: "" });
  }

  let fourEyes: Condition;
  if (release.signed_off) {
    fourEyes = {
      code: "FOUR_EYES",
      state: "met",
      reasons: [],
      detail: `Checked at sign-off: ${signedOffBy ?? "the approver who signed off"} decided none of the day's open cases.`,
    };
  } else if (role !== "approver") {
    fourEyes = {
      code: "FOUR_EYES",
      state: "na",
      reasons: [],
      detail: "Applies to the approver who signs off: they must have decided none of today's open cases.",
    };
  } else {
    const mine = release.blocking_for_me.filter((r) => r.code === "FOUR_EYES");
    fourEyes = mine.length
      ? { code: "FOUR_EYES", state: "unmet", reasons: mine, detail: "" }
      : { code: "FOUR_EYES", state: "met", reasons: [], detail: "You decided none of today's open cases." };
  }
  return [...out, fourEyes];
}

const ICONS: Record<State, "check" | "warn" | "dot"> = { met: "check", unmet: "warn", na: "dot" };
const WORDS: Record<State, string> = { met: "Met", unmet: "Not met", na: "For the signer" };

export function Conditions({
  release,
  overview,
  role,
  signedOffBy,
}: {
  release: ReleaseForMe;
  overview: Overview | undefined;
  role: RoleName;
  signedOffBy: string | null;
}) {
  const conditions = conditionsFor(release, overview, role, signedOffBy);
  const unmet = conditions.filter((c) => c.state === "unmet").length;
  return (
    <section className="so-block" aria-labelledby="so-h-conds">
      <div className="so-block-head">
        <h2 id="so-h-conds">Release conditions</h2>
        <span className="faint">
          {release.signed_off
            ? "as checked at sign-off"
            : unmet
              ? `${plural(unmet, "condition")} not met · checked again on the server at sign-off`
              : "checked again on the server at sign-off"}
        </span>
      </div>
      <ul className="so-conds">
        {conditions.map((c) => (
          <li key={c.code} data-condition={c.code} data-state={c.state}>
            <span className={`so-cond-state tone-${c.state}`}>
              <Icon name={ICONS[c.state]} />
              {WORDS[c.state]}
            </span>
            <div className="so-cond-body">
              <p className="so-cond-title">{releaseConditionLabel(c.code)}</p>
              {c.state === "unmet" ? (
                c.reasons.map((r, i) => (
                  <div key={`${r.code}-${i}`} className="so-cond-reason">
                    <p>{r.message}</p>
                    <CaseIdList ids={r.case_ids} />
                  </div>
                ))
              ) : (
                <p className="so-cond-detail">{c.detail}</p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
