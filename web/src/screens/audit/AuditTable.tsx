/**
 * One page of the audit log, newest first: the entry's number, when it was recorded, who
 * did it as which role, the action in words, the fund (when every fund is shown), the case
 * it concerns and one line of what it recorded. Each entry's full record and the server's
 * check of it open beneath it on demand.
 */
import { Fragment, useState } from "react";
import { Link } from "react-router";

import type { AuditLogEntry } from "../../api/types";
import { Icon } from "../../components/Icon";
import { timestamp } from "../../format";
import { auditActionLabel, roleLabel } from "../../vocabulary";
import { entryDetail } from "../signoff/AuditTrail";
import { EntryDetail } from "./EntryDetail";

function caseHref(entry: AuditLogEntry): string | null {
  if (!entry.case_id || !entry.fund) return null;
  const params = new URLSearchParams({ fund: entry.fund });
  if (entry.case_as_of) params.set("day", entry.case_as_of);
  params.set("case", entry.case_id);
  return `/cases?${params.toString()}`;
}

export function AuditTable({ entries, showFund }: { entries: AuditLogEntry[]; showFund: boolean }) {
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());
  const toggle = (seq: number) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  const columns = showFund ? 7 : 6;

  return (
    <div className="card al-card table-wrap">
      <table className="data-table al-table">
        <caption className="sr-only">Audit log entries, newest first</caption>
        <thead>
          <tr>
            <th scope="col" className="num">
              Entry
            </th>
            <th scope="col">Recorded</th>
            <th scope="col">Who</th>
            <th scope="col">Action</th>
            {showFund && <th scope="col">Fund</th>}
            <th scope="col">Case</th>
            <th scope="col">Detail</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const expanded = open.has(entry.seq);
            const href = caseHref(entry);
            const detail = entryDetail(entry);
            const panel = `al-entry-${entry.seq}`;
            return (
              <Fragment key={entry.seq}>
                <tr className={expanded ? "al-row open" : "al-row"} data-action={entry.action}>
                  <th scope="row" className="num">
                    <button
                      type="button"
                      className="al-seq"
                      aria-expanded={expanded}
                      aria-controls={panel}
                      aria-label={`Entry ${entry.seq}: ${expanded ? "hide" : "show"} its full record`}
                      onClick={() => toggle(entry.seq)}
                    >
                      <Icon name="chevron" className={expanded ? "al-chev open" : "al-chev"} />
                      <span className="mono">#{entry.seq}</span>
                    </button>
                  </th>
                  <td className="al-when fig">{timestamp(entry.ts)}</td>
                  <td>
                    {entry.actor}
                    {entry.role && <span className="faint"> ({roleLabel(entry.role)})</span>}
                  </td>
                  <td className="al-action">{auditActionLabel(entry.action)}</td>
                  {showFund && (
                    <td>
                      {entry.fund ? (
                        <span className="al-fund">{entry.fund}</span>
                      ) : (
                        <span className="faint">System</span>
                      )}
                    </td>
                  )}
                  <td>
                    {entry.case_id ? (
                      href ? (
                        <Link className="ov-case" to={href}>
                          {entry.case_id}
                        </Link>
                      ) : (
                        <span className="al-case">{entry.case_id}</span>
                      )
                    ) : null}
                  </td>
                  <td className="al-what muted">{detail}</td>
                </tr>
                {expanded && (
                  <tr className="al-detail-row" id={panel}>
                    <td colSpan={columns}>
                      <EntryDetail entry={entry} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
