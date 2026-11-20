/**
 * The audit log's filters on one row: whose entries (the fund being worked, or every fund
 * and the system's own), only the business day being worked, a date range, who, which
 * action, and a case. Each change goes into the address at once and returns to the newest
 * page; the case id is applied when Enter is pressed or the field is left.
 */
import { type FormEvent, useEffect, useRef, useState } from "react";

import { useAuditFacets } from "../../api/queries";
import { dayLabel } from "../../format";
import { useShortcut } from "../../keyboard/KeyboardProvider";
import { auditActionLabel } from "../../vocabulary";
import type { AuditView } from "./filters";

export interface FilterBarProps {
  view: AuditView;
  fund: string | null;
  asOf: string | null;
  /** Set one of the screen's filters in the address (empty removes it). */
  set: (key: "scope" | "only_day" | "from" | "to" | "actor" | "action" | "case", value: string) => void;
  clear: () => void;
  filtered: boolean;
}

export function FilterBar({ view, fund, asOf, set, clear, filtered }: FilterBarProps) {
  const facets = useAuditFacets(view.all ? null : fund);
  const [caseText, setCaseText] = useState(view.caseId);
  const caseRef = useRef<HTMLInputElement>(null);
  useShortcut(
    "/",
    () => {
      caseRef.current?.focus();
      caseRef.current?.select();
    },
    { description: "Filter the log by case", group: "Audit log", palette: true },
  );
  useEffect(() => setCaseText(view.caseId), [view.caseId]);

  const actors = [...(facets.data?.actors ?? [])];
  const actions = [...(facets.data?.actions ?? [])].sort((a, b) =>
    auditActionLabel(a).localeCompare(auditActionLabel(b), "en-GB"),
  );
  // Keep a chosen value listed even before the facets arrive or once it no longer occurs.
  if (view.actor && !actors.includes(view.actor)) actors.unshift(view.actor);
  if (view.action && !actions.includes(view.action)) actions.unshift(view.action);

  const applyCase = () => {
    const value = caseText.trim();
    if (value !== view.caseId) set("case", value);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    applyCase();
  };

  return (
    <form className="al-filters" role="search" aria-label="Filter the audit log" onSubmit={submit}>
      <label className="al-field">
        <span>Entries</span>
        <select value={view.all ? "all" : "fund"} onChange={(e) => set("scope", e.target.value === "all" ? "all" : "")}>
          <option value="fund">{fund ? `${fund} only` : "This fund only"}</option>
          <option value="all">Every fund and sign-ins</option>
        </select>
      </label>
      <label className="al-field al-check-field">
        <input
          type="checkbox"
          checked={view.onlyDay && !view.all}
          disabled={view.all || !asOf}
          onChange={(e) => set("only_day", e.target.checked ? "1" : "")}
        />
        <span>{asOf ? `Only ${dayLabel(asOf)}` : "Only the business day"}</span>
      </label>
      <label className="al-field">
        <span>From</span>
        <input type="date" className="input" value={view.from} max={view.to || undefined} onChange={(e) => set("from", e.target.value)} />
      </label>
      <label className="al-field">
        <span>To</span>
        <input type="date" className="input" value={view.to} min={view.from || undefined} onChange={(e) => set("to", e.target.value)} />
      </label>
      <label className="al-field">
        <span>Who</span>
        <select value={view.actor} onChange={(e) => set("actor", e.target.value)}>
          <option value="">Anyone</option>
          {actors.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
      </label>
      <label className="al-field">
        <span>Action</span>
        <select value={view.action} onChange={(e) => set("action", e.target.value)}>
          <option value="">Any action</option>
          {actions.map((a) => (
            <option key={a} value={a}>
              {auditActionLabel(a)}
            </option>
          ))}
        </select>
      </label>
      <label className="al-field">
        <span>Case</span>
        <input
          type="search"
          className="input"
          ref={caseRef}
          aria-keyshortcuts="/"
          value={caseText}
          placeholder="Case id"
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => setCaseText(e.target.value)}
          onKeyDown={(e) => {
            // The form has several fields and no submit button, so Enter does not submit it.
            if (e.key === "Enter") {
              e.preventDefault();
              applyCase();
            }
          }}
          onBlur={applyCase}
        />
      </label>
      {filtered && (
        <button type="button" className="btn quiet al-clear" onClick={clear}>
          Clear filters
        </button>
      )}
    </form>
  );
}
