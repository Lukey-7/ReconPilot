/**
 * Pane 2: the open case. What it is and what it costs, the rules' suggested cause beside the
 * AI's second opinion (with the disagreement flag), the AI's investigation steps, the draft
 * custodian query to copy, the case across the days it has been open, and its history from
 * the audit log. The decision bar sits at the foot of the pane, always in reach.
 */
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router";

import type { CaseDay, CaseDetail, CaseHistoryEntry, RoleName } from "../../api/types";
import { Icon } from "../../components/Icon";
import { StatusLabel } from "../../components/Labels";
import { Record, Records, Track } from "../../components/Paper";
import { ErrorLine } from "../../components/QueryState";
import { bp, count, dayLabel, money, plural, timestamp } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { FLAGS, auditActionLabel, causeLabel, roleLabel } from "../../vocabulary";
import { securityText } from "../overview/caseLinks";
import { DecisionBar } from "./DecisionBar";
import { FlagTag } from "./Flags";

const COPIED_MS = 2000;

function Section({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <section className="wb-section" aria-labelledby={id}>
      <div className="wb-section-h">
        <h3 id={id}>{title}</h3>
        {meta && <span className="wb-section-meta">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

function Confidence({ value }: { value: number | null }) {
  if (value == null) return null;
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="wb-conf">
      <span>Confidence <span className="fig">{pct}%</span></span>
      <Track value={pct} max={100} />
    </div>
  );
}

function Opinions({ detail }: { detail: CaseDetail }) {
  const c = detail.case;
  const accepted = c.ai_status === "ACCEPTED";
  let ai: ReactNode;
  if (accepted) {
    ai = (
      <>
        <p className="wb-op-cause">{causeLabel(c.ai_category)}</p>
        <Confidence value={c.ai_confidence} />
        <p className="wb-op-text">{c.ai_explanation}</p>
      </>
    );
  } else if (c.ai_status === "FALLBACK") {
    ai = (
      <p className="wb-op-text">
        The AI&rsquo;s answer did not pass the guardrails, so the rules&rsquo; cause stands
        {c.ai_fallback_reason ? `: ${c.ai_fallback_reason}` : "."}
      </p>
    );
  } else {
    ai = <p className="wb-op-text faint">No AI second opinion for this case: the AI is off for this fund or was not run.</p>;
  }
  return (
    <Section title="Suggested cause" meta="the rules first, the AI's second opinion beside it; the AI never changes a figure">
      {c.ai_flag ? (
        <p className="wb-disagree">
          <span className="status info">{c.ai_flag}</span>
        </p>
      ) : (
        accepted &&
        c.ai_category === c.category && (
          <p className="wb-agree-line">
            <Icon name="check" />
            The rules and the AI agree.
          </p>
        )
      )}
      <div className="wb-opinions">
        <article className="wb-opinion" aria-label="Rules engine">
          <p className="wb-op-who">
            <span>Rules engine</span>
            <span>deterministic</span>
          </p>
          <p className="wb-op-cause">{causeLabel(c.category)}</p>
          <Confidence value={c.confidence} />
          <p className="wb-op-text">{c.explanation}</p>
        </article>
        <article className="wb-opinion wb-opinion-ai" aria-label="AI second opinion">
          <p className="wb-op-who">
            <span>AI second opinion</span>
            {c.ai_model && (
              <span>
                {c.ai_model}
                {accepted ? ", passed the guardrails" : ""}
              </span>
            )}
          </p>
          {ai}
        </article>
      </div>
    </Section>
  );
}

function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand?.("copy") ?? false;
    area.remove();
    if (ok) resolve();
    else reject(new Error("copy failed"));
  });
}

function DraftQuery({ detail }: { detail: CaseDetail }) {
  const c = detail.case;
  const hasAi = c.ai_status === "ACCEPTED" && !!c.ai_query.trim();
  const [source, setSource] = useState<"ai" | "rules">(hasAi ? "ai" : "rules");
  const [copied, setCopied] = useState<"yes" | "failed" | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ids = useId();
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const shown = source === "ai" && hasAi ? "ai" : "rules";
  const text = shown === "ai" ? c.ai_query : c.query_draft;
  if (!text.trim() && !hasAi) return null;

  const copy = () => {
    copyText(text).then(
      () => setCopied("yes"),
      () => setCopied("failed"),
    );
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(null), COPIED_MS);
  };

  const tab = (value: "ai" | "rules", label: string, disabled = false) => (
    <button
      type="button"
      role="tab"
      id={`${ids}-${value}`}
      aria-selected={shown === value}
      aria-controls={`${ids}-panel`}
      tabIndex={shown === value ? 0 : -1}
      disabled={disabled}
      onClick={() => setSource(value)}
      onKeyDown={(e) => {
        if ((e.key === "ArrowRight" || e.key === "ArrowLeft") && hasAi) {
          e.preventDefault();
          const next = shown === "ai" ? "rules" : "ai";
          setSource(next);
          document.getElementById(`${ids}-${next}`)?.focus();
        }
      }}
    >
      {label}
    </button>
  );

  return (
    <Section title="Draft custodian query" meta="copy it into your email; nothing is sent from here">
      <div className="seg wb-tabs" role="tablist" aria-label="Draft from">
        {tab("ai", "AI draft", !hasAi)}
        {tab("rules", "Rules draft")}
      </div>
      <div className="wb-query" role="tabpanel" id={`${ids}-panel`} aria-labelledby={`${ids}-${shown}`}>
        <pre>{text}</pre>
        <span className="wb-copy">
          <span className="wb-copy-tip" role="status">
            {copied === "yes" ? "Copied" : copied === "failed" ? "Copy failed: select the text instead" : ""}
          </span>
          <button type="button" className="btn quiet" onClick={copy} data-copied={copied === "yes" || undefined}>
            {copied === "yes" && <Icon name="check" />}
            Copy query
          </button>
        </span>
      </div>
    </Section>
  );
}

function historyLine(entry: Extract<CaseHistoryEntry, { type: "audit" }>): { what: string; note: string } {
  const p = entry.payload ?? {};
  let what = auditActionLabel(entry.action);
  let note = "";
  const str = (key: string) => (typeof p[key] === "string" ? (p[key] as string) : "");
  switch (entry.action) {
    case "CASE_RECLASSIFIED":
      if (str("final")) what += ` as ${causeLabel(str("final"))}`;
      note = str("note");
      break;
    case "CASE_APPROVED":
    case "CASE_REJECTED":
      note = str("note");
      break;
    case "AI_CALL": {
      const model = str("model");
      if (model) what += ` (${model})`;
      if (p.fallback_used) note = `Fell back to the rules: ${str("fallback_reason")}`;
      else if (p.ai_category) note = `Read it as ${causeLabel(str("ai_category"))}${p.disagrees ? ", disagreeing with the rules" : ""}.`;
      break;
    }
    case "CASE_ESCALATED":
      note = Array.isArray(p.reasons) ? (p.reasons as string[]).join("; ") : "";
      break;
    case "CASE_AUTO_CLEARED":
    case "DECISION_VOIDED_BY_RERUN":
      note = str("reason");
      break;
    case "SLA_BREACHED":
      if (typeof p.age_days === "number" && typeof p.sla_days === "number") {
        note = `Open ${plural(p.age_days, "business day")} against an SLA of ${plural(p.sla_days, "day")}.`;
      }
      break;
    case "CASE_REOPENED":
      note = `Was ${causeLabel(str("was"))}, now ${causeLabel(str("now"))}.`;
      break;
  }
  return { what, note };
}

function dayFlags(d: CaseDay): string {
  const flags: string[] = [];
  if (d.material) flags.push(FLAGS.material);
  if (d.escalated) flags.push(FLAGS.escalated);
  if (d.sla_breached) flags.push(FLAGS.sla);
  return flags.join(", ");
}

/**
 * The case at the end of every day it has been in a run, oldest first: its status, the
 * cause read off it, its age, impact and flags. Each earlier day opens the case as it stood
 * then. Shown only once the case has more than one day; for a new case the facts above say
 * it all.
 */
function AcrossDays({ detail }: { detail: CaseDetail }) {
  const { href } = useWorkspace();
  const days = detail.days ?? [];
  const first = days[0];
  const last = days[days.length - 1];
  if (days.length < 2 || !first || !last) return null;
  const meta = last.is_open
    ? `first seen ${dayLabel(first.as_of)}, in ${plural(days.length, "run")}`
    : `first seen ${dayLabel(first.as_of)}, cleared ${dayLabel(last.as_of)}`;
  return (
    <Section title="Across days" meta={meta}>
      <div className="table-wrap">
        <table className="data-table wb-days">
          <caption className="sr-only">{detail.case_id} at the end of each day it was in a run, oldest first</caption>
          <thead>
            <tr>
              <th scope="col">Day</th>
              <th scope="col">Status</th>
              <th scope="col">Cause</th>
              <th scope="col" className="num">
                Age
              </th>
              <th scope="col" className="num">
                NAV impact
              </th>
              <th scope="col">Flags</th>
            </tr>
          </thead>
          <tbody>
            {days.map((d) => (
              <tr key={d.as_of} aria-current={d.as_of === detail.as_of ? "date" : undefined}>
                <th scope="row">
                  {d.as_of === detail.as_of ? (
                    dayLabel(d.as_of)
                  ) : (
                    <Link
                      to={href("/cases", { day: d.as_of, case: detail.case_id })}
                      title={`Open ${detail.case_id} as it stood on ${dayLabel(d.as_of)}`}
                    >
                      {dayLabel(d.as_of)}
                    </Link>
                  )}
                </th>
                <td>
                  <StatusLabel status={d.is_open ? d.status : "CLEARED"} />
                  {d.reviewed_by && d.is_open && d.status !== "PENDING" && (
                    <span className="wb-sub">by {d.reviewed_by}</span>
                  )}
                </td>
                <td>{causeLabel(d.cause)}</td>
                <td className="num">{plural(d.age_days, "day")}</td>
                <td className="num fig">{money(d.nav_impact, { signed: true })}</td>
                <td>{dayFlags(d) || <span className="faint">None</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

const SYSTEM_ACTIONS = new Set(["AI_CALL", "CASE_ESCALATED", "SLA_BREACHED", "CASE_AUTO_CLEARED", "CASE_REOPENED"]);

function History({ detail }: { detail: CaseDetail }) {
  const entries = detail.history.filter((h): h is Extract<CaseHistoryEntry, { type: "audit" }> => h.type === "audit");
  return (
    <Section title="Decision history" meta="from the audit log, oldest first">
      {entries.length === 0 ? (
        <p className="faint">Nothing recorded for this case yet.</p>
      ) : (
        <ol className="wb-history">
          {entries.map((h) => {
            const { what, note } = historyLine(h);
            const by = SYSTEM_ACTIONS.has(h.action)
              ? `during ${h.actor}'s run`
              : `${h.actor}${h.role ? `, ${roleLabel(h.role)}` : ""}`;
            return (
              <li key={h.seq}>
                <span className="wb-h-seq">#{h.seq}</span>
                <div>
                  <span className="wb-h-what">{what}</span> <span className="wb-h-by">{by}, {timestamp(h.at)}</span>
                  {note && <p className="wb-h-note">{note}</p>}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Section>
  );
}

export interface CasePaneProps {
  detail: CaseDetail | undefined;
  loading: boolean;
  error: unknown;
  retry: () => void;
  position: string;
  fund: string;
  asOf: string;
  role: RoleName;
  signedOffBy: string | null;
  beforeShortcut: () => boolean;
  nothingOpen: string;
  currency: string;
}

export function CasePane({
  detail,
  loading,
  error,
  retry,
  position,
  fund,
  asOf,
  role,
  signedOffBy,
  beforeShortcut,
  nothingOpen,
  currency,
}: CasePaneProps) {
  let body: ReactNode;
  if (error) body = <ErrorLine error={error} retry={retry} />;
  else if (loading) body = <p className="wb-empty" role="status">Loading the case…</p>;
  else if (!detail) body = <p className="wb-empty">{nothingOpen}</p>;
  else {
    const c = detail.case;
    body = (
      <div className="wb-case" key={detail.case_id}>
        {/* The case's lead card: what it costs, and where it stands. */}
        <div className="lead wb-lead">
          <div className="wb-lead-title">
            <h2 id="wb-h-case" tabIndex={-1}>
              {detail.case_id}
            </h2>
            <span className="wb-case-sec">
              {securityText(detail)}
              {detail.security_id && detail.security_name ? ` (${detail.security_id})` : ""}
            </span>
          </div>
          <dl className="wb-lead-impact">
            <dt className="lead-label">NAV impact</dt>
            <dd className="lead-figure">
              {money(c.nav_impact, { signed: true })} <span className="wb-lead-unit">{currency}</span>
            </dd>
            <dd className="lead-caption">
              <span className="fig">{bp(c.nav_impact_bp)}</span> of NAV
            </dd>
          </dl>
          <div className="lead-foot">
            <StatusLabel status={detail.is_open ? c.status : "CLEARED"} />
            {c.final_category && c.status === "RECLASSIFIED" && (
              <span className="wb-lead-as">as {causeLabel(c.final_category)}</span>
            )}
            {c.material && <FlagTag flag="material">Material: {bp(c.nav_impact_bp)} of NAV</FlagTag>}
            {c.escalated && (
              <FlagTag flag="escalated">
                Escalated{c.escalation_reason ? `: ${c.escalation_reason}, as recorded at escalation` : ""}
              </FlagTag>
            )}
            {c.sla_breached && (
              <FlagTag flag="sla">
                Past SLA: open {plural(c.age_days, "business day")} against {plural(c.sla_days, "day")}
              </FlagTag>
            )}
            {c.ai_flag && <FlagTag flag="ai" />}
          </div>
        </div>
        <Records className="wb-facts">
          <Record label="Gross exposure">
            <span className="fig">{money(c.gross_exposure)}</span> <span className="wb-unit">{currency}</span>
          </Record>
          <Record label="Age">
            <span className="wb-fact-line">
              <span className="fig">{count(c.age_days)}</span> business {c.age_days === 1 ? "day" : "days"}
              {c.first_seen && <span className="wb-sub"> since {dayLabel(c.first_seen)}</span>}
            </span>
            <Track
              value={c.age_days}
              max={Math.max(c.sla_days, c.age_days, 1)}
              tone={!detail.is_open ? "done" : c.sla_breached ? "late" : "ok"}
            />
          </Record>
          <Record label="SLA">
            {c.sla_breached ? (
              <span className="st tone-neg">
                <Icon name="clock" />
                Breached
              </span>
            ) : (
              <>
                <span className="fig">{count(c.sla_days)}</span> {c.sla_days === 1 ? "day" : "days"}
              </>
            )}
            <span className="wb-sub">, {c.material ? "material case" : "standard case"}</span>
          </Record>
        </Records>
        <Opinions detail={detail} />
        {c.ai_status === "ACCEPTED" && c.ai_steps.length > 0 && (
          <Section title="Investigation steps" meta="from the AI">
            <ol className="wb-steps">
              {c.ai_steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </Section>
        )}
        <DraftQuery key={detail.case_id} detail={detail} />
        <AcrossDays detail={detail} />
        <History detail={detail} />
      </div>
    );
  }

  return (
    <section className="wb-pane wb-case-pane" aria-label="Case">
      <div className="wb-pane-head">
        <span className="wb-pane-meta">{position}</span>
      </div>
      <div className="wb-pane-body wb-case-body">{body}</div>
      {detail && !error && !loading && (
        <DecisionBar
          key={detail.case_id}
          detail={detail}
          fund={fund}
          asOf={asOf}
          role={role}
          signedOffBy={signedOffBy}
          beforeShortcut={beforeShortcut}
        />
      )}
    </section>
  );
}
