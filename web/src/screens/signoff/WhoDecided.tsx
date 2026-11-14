/**
 * Who decided what: the day's open cases with their decision and the person (and role) who
 * made it, from the overview. A line above the table names each person and how many cases
 * they decided, so the four-eyes rule can be read at a glance: an approver named here
 * cannot also sign off.
 */
import type { ColumnDef } from "@tanstack/react-table";

import type { OverviewCase } from "../../api/types";
import { DataTable } from "../../components/DataTable";
import { StatusLabel } from "../../components/Labels";
import { MISSING, count, plural } from "../../format";
import { roleLabel, statusLabel } from "../../vocabulary";
import { CaseLink, currentCause, securityText } from "../overview/caseLinks";

interface Decider {
  user: string;
  role: string;
  cases: number;
}

/** Each person who decided an open case today, most cases first. */
export function decidersOf(cases: OverviewCase[]): Decider[] {
  const by = new Map<string, Decider>();
  for (const c of cases) {
    if (c.status === "PENDING" || !c.reviewed_by) continue;
    const d = by.get(c.reviewed_by) ?? { user: c.reviewed_by, role: c.reviewed_role, cases: 0 };
    d.cases += 1;
    by.set(c.reviewed_by, d);
  }
  return [...by.values()].sort((a, b) => b.cases - a.cases || a.user.localeCompare(b.user));
}

const columns: ColumnDef<OverviewCase, string>[] = [
  {
    id: "case",
    header: "Case",
    accessorFn: (c) => c.case_id,
    cell: ({ row }) => <CaseLink caseId={row.original.case_id} />,
  },
  { id: "security", header: "Security", accessorFn: (c) => securityText(c) },
  { id: "cause", header: "Cause", accessorFn: (c) => currentCause(c) },
  {
    id: "status",
    header: "Decision",
    accessorFn: (c) => statusLabel(c.status),
    cell: ({ row }) => <StatusLabel status={row.original.status} />,
  },
  {
    id: "by",
    header: "Decided by",
    accessorFn: (c) => (c.status === "PENDING" ? "" : c.reviewed_by),
    cell: ({ row }) => {
      const c = row.original;
      if (c.status === "PENDING" || !c.reviewed_by) return <span className="faint">{MISSING}</span>;
      return (
        <span>
          {c.reviewed_by} <span className="faint">({roleLabel(c.reviewed_role)})</span>
        </span>
      );
    },
  },
  {
    id: "note",
    header: "Note",
    accessorFn: (c) => c.review_note,
    enableSorting: false,
    meta: { className: "so-note" },
    cell: ({ row }) => {
      const note = row.original.review_note;
      return note ? (
        <span className="muted" title={note}>
          {note}
        </span>
      ) : (
        <span className="faint">{MISSING}</span>
      );
    },
  },
];

export function WhoDecided({ cases }: { cases: OverviewCase[] }) {
  const deciders = decidersOf(cases);
  const pending = cases.filter((c) => c.status === "PENDING").length;
  return (
    <section className="so-block" aria-labelledby="so-h-who">
      <div className="so-block-head">
        <h2 id="so-h-who">Who decided what</h2>
        <span className="faint">
          {cases.length ? `${plural(cases.length, "open case")}${pending ? `, ${count(pending)} pending` : ""}` : "no open cases"}
        </span>
      </div>
      {deciders.length > 0 && (
        <ul className="so-deciders" aria-label="People who decided cases today">
          {deciders.map((d) => (
            <li key={d.user}>
              <strong>{d.user}</strong> <span className="faint">{roleLabel(d.role)}</span>{" "}
              <span className="fig">{plural(d.cases, "case")}</span>
            </li>
          ))}
        </ul>
      )}
      {cases.length > 0 ? (
        <DataTable
          data={cases}
          columns={columns}
          caption="Open cases and who decided them"
          captionHidden
          getRowId={(c) => c.case_id}
          className="so-who-table"
        />
      ) : (
        <p className="muted">No case is open for this day, so there is nothing to decide.</p>
      )}
    </section>
  );
}
