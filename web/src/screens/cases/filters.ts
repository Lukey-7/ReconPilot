/**
 * The queue's filters and search, kept in the address (`/cases?fund=&day=&status=PENDING&material=true&q=`)
 * under the API's own parameter names, so a filtered queue can be reloaded or shared and the
 * request to the server is the address's filters as they stand.
 */
import type { CaseFilters } from "../../api/queries";
import { AGE_BUCKETS, CAUSES, STATUSES } from "../../vocabulary";

/** The flags that filter to flagged cases only (a toggle, never "only unflagged"). */
export const FLAG_FILTERS = ["material", "escalated", "sla", "ai_disagrees"] as const;
export type FlagFilter = (typeof FLAG_FILTERS)[number];

/** Every address parameter the queue's filters use. */
export const FILTER_PARAMS = ["status", "category", "age", "q", ...FLAG_FILTERS] as const;

/** Statuses a queue can be filtered by: the engine's four (Cleared cases are never in the queue). */
export const QUEUE_STATUSES = STATUSES.filter((s) => s !== "CLEARED");

function oneOf(value: string | null, allowed: readonly string[]): string | undefined {
  return value != null && allowed.includes(value) ? value : undefined;
}

/** The filters in the address. Unknown values are ignored rather than sent. */
export function filtersFrom(params: URLSearchParams): CaseFilters {
  const filters: CaseFilters = {};
  const status = oneOf(params.get("status"), QUEUE_STATUSES);
  if (status) filters.status = status;
  const category = oneOf(params.get("category"), CAUSES);
  if (category) filters.category = category;
  const age = oneOf(params.get("age"), Object.keys(AGE_BUCKETS));
  if (age) filters.age = age;
  for (const flag of FLAG_FILTERS) if (params.get(flag) === "true") filters[flag] = true;
  const q = params.get("q")?.trim();
  if (q) filters.q = q.slice(0, 200);
  return filters;
}

/** The address parameters with one filter changed (undefined or false removes it). */
export function withFilter(
  params: URLSearchParams,
  key: (typeof FILTER_PARAMS)[number],
  value: string | boolean | undefined,
): URLSearchParams {
  const next = new URLSearchParams(params);
  if (value === undefined || value === false || value === "") next.delete(key);
  else next.set(key, value === true ? "true" : value);
  return next;
}

/** The address parameters with every filter removed (fund, day and the open case stay). */
export function withoutFilters(params: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(params);
  for (const key of FILTER_PARAMS) next.delete(key);
  return next;
}

export function hasFilters(filters: CaseFilters): boolean {
  return Object.keys(filters).length > 0;
}
