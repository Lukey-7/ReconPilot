/**
 * The audit log (spec section 8; section 10, screen 6), from `GET /api/audit`.
 *
 * One job: let anyone check what was done, by whom and when, and that the record has not
 * been altered. The lead card carries the chain's integrity and the two actions: "Verify
 * chain", the one primary, re-checks every hash on the server (which records that it did),
 * and "Export CSV", a quiet chip, downloads the matching entries in chain order. Then the
 * filters, and the entries, newest first, a page at a time, each entry's full record and the
 * server's check of it on demand. Filters and the page live in the address, so a view can
 * be shared.
 */
import "./audit.css";

import { useCallback } from "react";
import { useSearchParams } from "react-router";

import { useAuditExport, useAuditLog, useVerifyChain } from "../../api/queries";
import type { AuditFilters } from "../../api/types";
import { useUser } from "../../auth/AuthContext";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { count, dayLabel, plural } from "../../format";
import { useCommand } from "../../keyboard/KeyboardProvider";
import { useWorkspace } from "../../shell/workspace";
import { AUDIT_EXPORT } from "../../vocabulary";
import { AuditTable } from "./AuditTable";
import { ChainLead } from "./ChainVerdict";
import { FilterBar, type FilterBarProps } from "./FilterBar";
import { apiFilters, isFiltered, viewFrom, withAuditParam, withoutAuditFilters } from "./filters";

function ExportButton({ filters }: { filters: AuditFilters }) {
  const exporting = useAuditExport();
  useCommand("Export the audit log as CSV", () => exporting.mutate(filters), {
    group: "Audit log",
    enabled: !exporting.isPending,
    keywords: "download entries hashes",
  });
  return (
    <>
      <button
        type="button"
        className="btn quiet"
        disabled={exporting.isPending}
        aria-busy={exporting.isPending}
        title="Download the entries these filters match, oldest first, with their hashes"
        onClick={() => exporting.mutate(filters)}
      >
        {exporting.isPending ? "Preparing…" : AUDIT_EXPORT}
      </button>
      <p className="al-status faint" role="status">
        {exporting.isSuccess ? `Downloaded ${exporting.data.filename}.` : ""}
      </p>
      {exporting.isError && <ErrorLine error={exporting.error} />}
    </>
  );
}

interface PagerProps {
  shown: number;
  total: number;
  newer: number;
  hasNewer: boolean;
  newerBefore: number | null;
  nextBefore: number | null;
  go: (before: number | null) => void;
}

function Pager({ shown, total, newer, hasNewer, newerBefore, nextBefore, go }: PagerProps) {
  return (
    <nav className="al-pager" aria-label="Pages of the audit log">
      <p className="al-position" role="status">
        {count(newer + 1)} to {count(newer + shown)} of {plural(total, "entry", "entries")}, newest first
      </p>
      <div className="al-page-buttons">
        <button type="button" className="btn quiet" disabled={!hasNewer} onClick={() => go(null)}>
          Newest
        </button>
        <button type="button" className="btn quiet" disabled={!hasNewer} onClick={() => go(newerBefore)}>
          Newer
        </button>
        <button type="button" className="btn quiet" disabled={nextBefore == null} onClick={() => go(nextBefore)}>
          Older
        </button>
      </div>
    </nav>
  );
}

export function AuditScreen() {
  const [params, setParams] = useSearchParams();
  const { fund, asOf } = useWorkspace();
  const user = useUser();
  const verify = useVerifyChain();
  const view = viewFrom(params);
  const fundCode = fund?.code ?? null;
  const filters = apiFilters(view, fundCode, asOf);
  const query = useAuditLog(filters, view.before);
  const page = query.data;
  const filtered = isFiltered(view);
  useCommand("Verify the audit chain", () => verify.mutate(), {
    group: "Audit log",
    enabled: !verify.isPending,
    keywords: "check hashes tamper",
  });

  const set = useCallback<FilterBarProps["set"]>(
    (key, value) => setParams(withAuditParam(params, key, value)),
    [params, setParams],
  );
  const clear = useCallback(() => setParams(withoutAuditFilters(params)), [params, setParams]);
  const go = useCallback(
    (before: number | null) => setParams(withAuditParam(params, "before", before ? String(before) : "")),
    [params, setParams],
  );

  let scope: string;
  if (view.all || !fund) scope = "Every fund, with sign-ins and the system's own entries";
  else if (view.onlyDay && asOf) scope = `${fund.name}, ${dayLabel(asOf)} only`;
  else scope = `${fund.name}, every day`;

  let body;
  if (query.isPending) body = <Loading label="Loading the audit log" />;
  else if (query.isError) body = <ErrorLine error={query.error} retry={() => void query.refetch()} />;
  else if (page && page.entries.length === 0) {
    body = <Empty>{filtered ? "No entry matches these filters." : "Nothing has been recorded here yet."}</Empty>;
  } else if (page) {
    body = (
      <>
        <AuditTable entries={page.entries} showFund={view.all} />
        <Pager
          shown={page.entries.length}
          total={page.total}
          newer={page.newer}
          hasNewer={page.has_newer}
          newerBefore={page.newer_before}
          nextBefore={page.next_before}
          go={go}
        />
      </>
    );
  }

  return (
    <section className="screen al-screen">
      <ScreenHeader title="Audit log">
        <p className="muted">
          {scope}
          {page ? `. The log holds ${plural(page.latest_seq, "entry", "entries")}.` : ""}
        </p>
      </ScreenHeader>
      <ChainLead
        check={verify.data}
        error={verify.error}
        me={user.username}
        actions={
          <div className="al-actions" role="group" aria-label="Check and export the log">
            <button
              type="button"
              className="btn primary"
              disabled={verify.isPending}
              aria-busy={verify.isPending}
              title="Re-check every entry's hash on the server"
              onClick={() => verify.mutate()}
            >
              {verify.isPending ? "Verifying…" : "Verify chain"}
            </button>
            <ExportButton filters={filters} />
          </div>
        }
      />
      <FilterBar view={view} fund={fundCode} asOf={asOf} set={set} clear={clear} filtered={filtered} />
      <section className="al-block" aria-label="Matching entries">
        {body}
      </section>
    </section>
  );
}
