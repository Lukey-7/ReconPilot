/**
 * Pane 1: the queue. The day's open cases, largest absolute NAV impact first (the server's
 * order), with search and filters above and the flags as labels on each row. A row opens
 * its case by click or Enter; j/k and the arrows move between rows.
 */
import { createColumnHelper } from "@tanstack/react-table";
import { type FocusEvent, type KeyboardEvent, type RefObject, useEffect, useMemo, useState } from "react";

import type { CaseFilters } from "../../api/queries";
import type { QueueCase } from "../../api/types";
import { DataTable } from "../../components/DataTable";
import { Icon } from "../../components/Icon";
import { Kbd } from "../../components/Kbd";
import { StatusLabel } from "../../components/Labels";
import { ErrorLine } from "../../components/QueryState";
import { bp, count, money, plural } from "../../format";
import { AGE_BUCKETS, CAUSES, CAUSE_LABELS, FLAGS, STATUS_LABELS, ageBucketLabel } from "../../vocabulary";
import { currentCause, securityText } from "../overview/caseLinks";
import { FLAG_FILTERS, type FlagFilter, QUEUE_STATUSES, hasFilters } from "./filters";
import { Flags } from "./Flags";

const SEARCH_DELAY_MS = 250;

const FLAG_FILTER_LABELS: Record<FlagFilter, string> = {
  material: FLAGS.material,
  escalated: FLAGS.escalated,
  sla: FLAGS.sla,
  ai_disagrees: FLAGS.ai,
};

const helper = createColumnHelper<QueueCase>();

const columns = [
  helper.accessor("case_id", {
    header: "Case",
    cell: (c) => {
      const row = c.row.original;
      return (
        <div className="wb-q-case">
          <span className="wb-q-id">{row.case_id}</span>
          <span className="wb-q-sec">{securityText(row)}</span>
          <Flags c={row} />
        </div>
      );
    },
  }),
  // Sorted by size whichever way the money moves: the absolute impact is what ranks a break.
  helper.accessor((row) => Math.abs(row.nav_impact), {
    id: "impact",
    header: "NAV impact",
    sortDescFirst: true,
    meta: { numeric: true },
    cell: (c) => (
      <div className="wb-q-fig">
        <span>{money(c.row.original.nav_impact, { signed: true })}</span>
        <span className="wb-q-sub">{bp(c.row.original.nav_impact_bp)}</span>
      </div>
    ),
  }),
  helper.accessor("age_days", {
    header: "Age",
    sortDescFirst: true,
    meta: { numeric: true },
    cell: (c) => (
      <>
        {count(c.getValue())}
        <span className="sr-only"> business {c.getValue() === 1 ? "day" : "days"}</span>
        <span className="wb-q-unit" aria-hidden="true">
          d
        </span>
      </>
    ),
  }),
  helper.accessor("status", {
    header: "Status",
    enableSorting: false,
    cell: (c) => (
      <div className="wb-q-status">
        <StatusLabel status={c.getValue()} />
        <span className="wb-q-sub">{currentCause(c.row.original)}</span>
      </div>
    ),
  }),
];

/** The search box: types freely, and tells the screen after a short pause. */
function Search({
  value,
  onChange,
  inputRef,
}: {
  value: string;
  onChange: (q: string) => void;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  const [text, setText] = useState(value);
  const [lastValue, setLastValue] = useState(value);
  // The address changed from elsewhere (a cleared filter, back and forward): follow it.
  if (value !== lastValue) {
    setLastValue(value);
    setText(value);
  }

  useEffect(() => {
    if (text.trim() === value) return;
    const timer = setTimeout(() => onChange(text.trim()), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [text, value, onChange]);

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      if (text) {
        setText("");
        onChange("");
      } else event.currentTarget.blur();
    } else if (event.key === "Enter") {
      event.preventDefault();
      onChange(text.trim());
    }
  };

  return (
    <div className="wb-search">
      <label htmlFor="wb-q" className="sr-only">
        Search cases by case id, security id or security name
      </label>
      <input
        id="wb-q"
        ref={inputRef}
        type="search"
        className="input"
        placeholder="Case, security id or name"
        autoComplete="off"
        spellCheck={false}
        aria-keyshortcuts="/"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <Kbd keys="/" />
    </div>
  );
}

export interface QueuePaneProps {
  cases: QueueCase[] | undefined;
  loading: boolean;
  fetching: boolean;
  error: unknown;
  retry: () => void;
  notReady: string | null;
  filters: CaseFilters;
  setFilter: (key: keyof CaseFilters, value: string | boolean | undefined) => void;
  clearFilters: () => void;
  openId: string | null;
  onOpen: (caseId: string) => void;
  onOrderChange: (ids: string[]) => void;
  searchRef: RefObject<HTMLInputElement | null>;
  tableRef: RefObject<HTMLDivElement | null>;
  /** A row took focus (by Tab, click or the keyboard cursor): it is now the cursor. */
  onRowFocus: (caseId: string) => void;
}

export function QueuePane({
  cases,
  loading,
  fetching,
  error,
  retry,
  notReady,
  filters,
  setFilter,
  clearFilters,
  openId,
  onOpen,
  onOrderChange,
  searchRef,
  tableRef,
  onRowFocus,
}: QueuePaneProps) {
  const filtered = hasFilters(filters);
  const meta = useMemo(() => {
    if (!cases) return "";
    const pending = cases.filter((c) => c.status === "PENDING").length;
    return `${plural(cases.length, filtered ? "case shown" : "open case", filtered ? "cases shown" : "open cases")}, ${count(pending)} pending`;
  }, [cases, filtered]);

  let body;
  if (notReady) body = <p className="wb-empty">{notReady}</p>;
  else if (error) body = <ErrorLine error={error} retry={retry} />;
  else if (loading || !cases) body = <p className="wb-empty" role="status">Loading the queue…</p>;
  else
    body = (
      <div
        ref={tableRef}
        className="wb-q-table"
        aria-busy={fetching || undefined}
        onFocus={(event: FocusEvent<HTMLDivElement>) => {
          const row = event.target instanceof HTMLElement ? event.target.closest<HTMLElement>("tr[data-row-id]") : null;
          if (row?.dataset.rowId) onRowFocus(row.dataset.rowId);
        }}
      >
        <DataTable
          data={cases}
          columns={columns}
          caption="Open cases, largest absolute NAV impact first"
          captionHidden
          getRowId={(row) => row.case_id}
          selectedId={openId}
          onActivate={(row) => onOpen(row.case_id)}
          onOrderChange={onOrderChange}
          className="wb-queue list-enter"
          empty={
            filtered ? (
              <>
                No open case matches these filters.{" "}
                <button type="button" className="btn ghost" onClick={clearFilters}>
                  Clear filters
                </button>
              </>
            ) : (
              "No open cases on this day: every break is matched or cleared."
            )
          }
        />
      </div>
    );

  return (
    <section className="wb-pane wb-queue-pane" aria-labelledby="wb-h-queue">
      <div className="wb-pane-head">
        <h2 id="wb-h-queue">Queue</h2>
        <span className="wb-pane-meta" aria-live="polite">
          {meta}
        </span>
      </div>
      <div className="wb-tools" role="search" aria-label="Filter the queue">
        <Search value={filters.q ?? ""} onChange={(q) => setFilter("q", q || undefined)} inputRef={searchRef} />
        <div className="wb-selects">
          <label className="wb-select">
            <span className="sr-only">Status</span>
            <select value={filters.status ?? ""} onChange={(e) => setFilter("status", e.target.value || undefined)}>
              <option value="">Any status</option>
              {QUEUE_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </label>
          <label className="wb-select">
            <span className="sr-only">Cause</span>
            <select value={filters.category ?? ""} onChange={(e) => setFilter("category", e.target.value || undefined)}>
              <option value="">Any cause</option>
              {CAUSES.map((c) => (
                <option key={c} value={c}>
                  {CAUSE_LABELS[c]}
                </option>
              ))}
            </select>
          </label>
          <label className="wb-select">
            <span className="sr-only">Age</span>
            <select value={filters.age ?? ""} onChange={(e) => setFilter("age", e.target.value || undefined)}>
              <option value="">Any age</option>
              {Object.keys(AGE_BUCKETS).map((b) => (
                <option key={b} value={b}>
                  {ageBucketLabel(b)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="wb-chips" role="group" aria-label="Only cases flagged">
          {FLAG_FILTERS.map((flag) => (
            <button
              key={flag}
              type="button"
              className="wb-chip"
              aria-pressed={!!filters[flag]}
              onClick={() => setFilter(flag, !filters[flag])}
            >
              {filters[flag] && <Icon name="check" />}
              {FLAG_FILTER_LABELS[flag]}
            </button>
          ))}
          {filtered && (
            <button type="button" className="btn ghost wb-clear" onClick={clearFilters}>
              Clear filters
            </button>
          )}
        </div>
      </div>
      <div className="wb-pane-body wb-q-body">{body}</div>
    </section>
  );
}
