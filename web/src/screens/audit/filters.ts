/**
 * The audit log screen's filters, kept in the address beside the workspace's fund and day
 * so a filtered view can be shared:
 *
 * - `scope=all`: every fund and the system's own entries (sign-ins, users, chain checks);
 *   otherwise the fund being worked;
 * - `only_day=1`: only the business day being worked (that fund's trail for the day);
 * - `from`, `to`: days in the user's own time zone, sent to the server as instants;
 * - `actor`, `action`, `case`: as the API names them;
 * - `before`: the page's cursor.
 */
import type { AuditFilters } from "../../api/types";

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The screen's own keys in the address (the workspace's `fund` and `day` are not among them). */
export const AUDIT_PARAMS = ["scope", "only_day", "from", "to", "actor", "action", "case", "before"] as const;

export interface AuditView {
  /** Every fund and system entry, rather than the fund being worked. */
  all: boolean;
  onlyDay: boolean;
  from: string;
  to: string;
  actor: string;
  action: string;
  caseId: string;
  before: number | null;
}

export function viewFrom(params: URLSearchParams): AuditView {
  const day = (key: string) => {
    const value = params.get(key) ?? "";
    return ISO_DAY.test(value) ? value : "";
  };
  const before = Number(params.get("before"));
  return {
    all: params.get("scope") === "all",
    onlyDay: params.get("only_day") === "1",
    from: day("from"),
    to: day("to"),
    actor: params.get("actor") ?? "",
    action: params.get("action") ?? "",
    caseId: params.get("case") ?? "",
    before: Number.isInteger(before) && before > 0 ? before : null,
  };
}

/** Whether any filter narrows the log beyond the fund being worked. */
export function isFiltered(view: AuditView): boolean {
  return view.onlyDay || !!(view.from || view.to || view.actor || view.action || view.caseId);
}

/** The start of a local calendar day as an instant (`2026-11-13` -> its local midnight, in UTC). */
export function localDayStart(isoDay: string): string {
  const [y, m, d] = isoDay.split("-").map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1, 0, 0, 0, 0).toISOString();
}

/** The last moment of a local calendar day as an instant. */
export function localDayEnd(isoDay: string): string {
  const [y, m, d] = isoDay.split("-").map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1, 23, 59, 59, 999).toISOString();
}

/** The filters the API is asked for, from what the screen shows. */
export function apiFilters(view: AuditView, fund: string | null, asOf: string | null): AuditFilters {
  const filters: AuditFilters = {};
  if (!view.all && fund) {
    filters.fund = fund;
    if (view.onlyDay && asOf) filters.as_of = asOf;
  }
  if (view.from) filters.from = localDayStart(view.from);
  if (view.to) filters.to = localDayEnd(view.to);
  if (view.actor) filters.actor = view.actor;
  if (view.action) filters.action = view.action;
  if (view.caseId) filters.case = view.caseId;
  return filters;
}

/** The address with one filter changed (empty removes it). Any change of filter returns to the newest page. */
export function withAuditParam(params: URLSearchParams, key: (typeof AUDIT_PARAMS)[number], value: string): URLSearchParams {
  const next = new URLSearchParams(params);
  if (value) next.set(key, value);
  else next.delete(key);
  if (key !== "before") next.delete("before");
  return next;
}

/** The address without the filters that narrow the log (the scope, fund and day stay). */
export function withoutAuditFilters(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of AUDIT_PARAMS) if (key !== "scope") next.delete(key);
  return next;
}
