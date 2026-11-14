/**
 * The day's audit trail (the Ledger's sign-off page): every entry the day wrote to the
 * hash-chained audit log, oldest first, with the server's verdict on the whole chain. The
 * latest entries show; the earlier ones wait behind an expander, so the trail stays calm
 * on a busy day. Each entry says who did what, as whom, when, and to which case.
 */
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { useDayAudit } from "../../api/queries";
import type { AuditEntry } from "../../api/types";
import { Icon } from "../../components/Icon";
import { ErrorLine, Loading } from "../../components/QueryState";
import { count, plural, timestamp } from "../../format";
import { EXPORT_NAMES, auditActionLabel, causeLabel, releaseReasonLabel, roleLabel } from "../../vocabulary";
import { useWorkspace } from "../../shell/workspace";
import { CaseLink } from "../overview/caseLinks";

/** How many of the latest entries show before the rest go behind "Show earlier entries". */
export const ENTRIES_SHOWN = 10;

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** One short line of what an entry recorded, in plain words; empty when the action says it all. */
export function entryDetail(entry: AuditEntry): string {
  const p = entry.payload ?? {};
  switch (entry.action) {
    case "CASE_APPROVED":
    case "CASE_REJECTED":
    case "CASE_RECLASSIFIED": {
      const parts: string[] = [];
      if (entry.action === "CASE_RECLASSIFIED" && text(p.final)) parts.push(`as ${causeLabel(text(p.final))}`);
      if (text(p.note)) parts.push(`“${text(p.note)}”`);
      return parts.join(", ");
    }
    case "FILES_UPLOADED":
      return Array.isArray(p.files) ? plural(p.files.length, "file") : "";
    case "VALIDATION_PASSED":
    case "VALIDATION_FAILED": {
      const errors = num(p.errors);
      const warnings = num(p.warnings);
      if (errors == null || warnings == null) return "";
      return `${plural(errors, "error")}, ${plural(warnings, "warning")}`;
    }
    case "RUN_STARTED":
      return p.rerun === true ? "a re-run" : "";
    case "CASES_RAISED": {
      const breaks = num(p.breaks);
      const open = num(p.open_cases);
      return breaks != null && open != null ? `${plural(breaks, "break")}, ${plural(open, "open case")}` : "";
    }
    case "RUN_FINISHED": {
      const open = num(p.open_cases);
      const fresh = num(p.new_cases);
      if (open == null) return "";
      return fresh != null ? `${plural(open, "open case")}, ${count(fresh)} new` : plural(open, "open case");
    }
    case "SIGN_OFF_BLOCKED": {
      if (Array.isArray(p.reasons)) {
        return p.reasons
          .map((r) => (r && typeof r === "object" && "code" in r ? releaseReasonLabel(text(r.code)) : ""))
          .filter(Boolean)
          .join(", ");
      }
      return text(p.reason);
    }
    case "DAY_SIGNED_OFF": {
      const cases = num(p.cases);
      return cases != null ? plural(cases, "open case") : "";
    }
    case "CASE_ESCALATED":
      return Array.isArray(p.reasons) ? p.reasons.map(text).filter(Boolean).join("; ") : "";
    case "SLA_BREACHED": {
      const age = num(p.age_days);
      const sla = num(p.sla_days);
      return age != null && sla != null ? `open ${plural(age, "business day")}, SLA ${count(sla)}` : "";
    }
    case "CASE_AUTO_CLEARED":
      return text(p.reason);
    case "CASE_REOPENED":
      return text(p.now) ? `now ${causeLabel(text(p.now))}` : "";
    case "AI_CALL": {
      const model = text(p.model);
      return p.fallback_used === true ? `${model}, the rules stand` : model;
    }
    case "AI_UNAVAILABLE":
      return text(p.reason);
    case "PERMISSION_DENIED":
      return text(p.attempted) ? `tried to ${text(p.attempted)}` : "";
    case "RUN_FAILED":
      return text(p.error);
    case "EXPORT_DOWNLOADED": {
      const name = EXPORT_NAMES[text(p.export)] ?? text(p.export);
      const rows = num(p.rows);
      const file = text(p.filename);
      return [name, file, rows != null ? plural(rows, "entry", "entries") : ""].filter(Boolean).join(", ");
    }
    case "AUDIT_CHAIN_VERIFIED": {
      const entries = num(p.entries);
      if (p.intact === true) return entries != null ? `intact, ${plural(entries, "entry", "entries")} checked` : "intact";
      const at = num(p.broken_at);
      return at != null ? `broken at entry #${at}` : "broken";
    }
    case "SIGN_IN_FAILED":
      return text(p.reason);
    case "ACCOUNT_LOCKED": {
      const failed = num(p.failed_logins);
      return failed != null ? `after ${plural(failed, "failed sign-in")}` : "";
    }
    case "USER_CREATED":
      return [text(p.username), text(p.role) ? roleLabel(text(p.role)).toLowerCase() : ""].filter(Boolean).join(", ");
    case "FUND_CREATED":
      return [text(p.code), text(p.name)].filter(Boolean).join(", ");
    default:
      return "";
  }
}

function Entry({ entry }: { entry: AuditEntry }) {
  const detail = entryDetail(entry);
  return (
    <li className="so-entry" data-action={entry.action}>
      <span className="so-entry-seq fig" title={`Hash ${entry.hash}`}>
        #{entry.seq}
      </span>
      <span className="so-entry-when faint">{timestamp(entry.ts)}</span>
      <span className="so-entry-what">
        <strong>{auditActionLabel(entry.action)}</strong>
        {entry.case_id && (
          <>
            {" "}
            <CaseLink caseId={entry.case_id} />
          </>
        )}
        {detail && <span className="muted"> · {detail}</span>}
      </span>
      <span className="so-entry-who">
        {entry.actor}
        {entry.role && <span className="faint"> ({roleLabel(entry.role)})</span>}
      </span>
    </li>
  );
}

function ChainLine({ ok, brokenAt }: { ok: boolean; brokenAt: number | null }) {
  if (ok) {
    return (
      <p className="so-chain tone-met">
        <Icon name="check" />
        <span>Chain verified on the server: every entry&rsquo;s hash checks out.</span>
      </p>
    );
  }
  return (
    <p className="so-chain tone-broken" role="alert">
      <Icon name="warn" />
      <span>
        Chain broken at entry #{brokenAt ?? "?"}. The log may have been altered after it was written; report it
        to your control team before relying on it.
      </span>
    </p>
  );
}

export function AuditTrail({ fund, asOf }: { fund: string; asOf: string }) {
  const { href } = useWorkspace();
  const query = useDayAudit(fund, asOf);
  const audit = query.data;

  let body;
  if (query.isPending) body = <Loading label="Loading the audit trail" />;
  else if (query.isError) {
    body =
      query.error instanceof ApiError && query.error.status === 404 ? (
        <p className="muted">Nothing has been recorded for this day yet.</p>
      ) : (
        <ErrorLine error={query.error} retry={() => void query.refetch()} />
      );
  } else if (audit) {
    const earlier = audit.entries.slice(0, Math.max(0, audit.entries.length - ENTRIES_SHOWN));
    const latest = audit.entries.slice(earlier.length);
    body = (
      <>
        <ChainLine ok={audit.chain_ok} brokenAt={audit.broken_at} />
        {earlier.length > 0 && (
          <details className="so-more so-earlier">
            <summary>Show {plural(earlier.length, "earlier entry", "earlier entries")}</summary>
            <ol className="so-entries" aria-label="Earlier entries">
              {earlier.map((e) => (
                <Entry key={e.seq} entry={e} />
              ))}
            </ol>
          </details>
        )}
        {latest.length > 0 ? (
          <ol className="so-entries" aria-label="Latest entries">
            {latest.map((e) => (
              <Entry key={e.seq} entry={e} />
            ))}
          </ol>
        ) : (
          <p className="muted">Nothing has been recorded for this day yet.</p>
        )}
      </>
    );
  }

  return (
    <section className="so-block" aria-labelledby="so-h-audit">
      <div className="so-block-head">
        <h2 id="so-h-audit">Audit trail</h2>
        {audit && <span className="faint">{plural(audit.entries.length, "entry", "entries")} for this day</span>}
        <Link className="so-log-link" to={href("/audit", { only_day: "1" })}>
          Open in the audit log
        </Link>
      </div>
      {body}
    </section>
  );
}
