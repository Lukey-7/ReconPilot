/**
 * Query keys and hooks for every read the front end makes (TanStack Query).
 *
 * Keys are hierarchical so one fund-and-day prefix invalidates everything about that day
 * after a decision or a sign-off: `invalidateDay(queryClient, fund, asOf)`.
 */
import { QueryClient, keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, seg } from "./client";
import type {
  CaseDetail,
  Day,
  DayAudit,
  DaysList,
  DecisionRequest,
  FundSummary,
  Overview,
  QueueCase,
  ReleaseForMe,
} from "./types";

export const queryKeys = {
  me: ["me"] as const,
  funds: ["funds"] as const,
  days: (fund: string) => ["funds", fund, "days"] as const,
  day: (fund: string, asOf: string) => ["funds", fund, "day", asOf] as const,
  release: (fund: string, asOf: string) => ["funds", fund, "day", asOf, "release"] as const,
  overview: (fund: string, asOf: string) => ["funds", fund, "day", asOf, "overview"] as const,
  audit: (fund: string, asOf: string) => ["funds", fund, "day", asOf, "audit"] as const,
  cases: (fund: string, asOf: string, filters?: Record<string, unknown>) =>
    filters ? (["funds", fund, "day", asOf, "cases", filters] as const) : (["funds", fund, "day", asOf, "cases"] as const),
  case: (fund: string, caseId: string, asOf?: string) => ["funds", fund, "case", caseId, asOf ?? null] as const,
};

export const paths = {
  me: "/api/auth/me",
  login: "/api/auth/login",
  logout: "/api/auth/logout",
  funds: "/api/funds",
  days: (fund: string) => `/api/funds/${seg(fund)}/days`,
  day: (fund: string, asOf: string) => `/api/funds/${seg(fund)}/days/${seg(asOf)}`,
  release: (fund: string, asOf: string) => `/api/funds/${seg(fund)}/days/${seg(asOf)}/release`,
  overview: (fund: string, asOf: string) => `/api/funds/${seg(fund)}/days/${seg(asOf)}/overview`,
  signoff: (fund: string, asOf: string) => `/api/funds/${seg(fund)}/days/${seg(asOf)}/signoff`,
  audit: (fund: string, asOf: string) => `/api/funds/${seg(fund)}/days/${seg(asOf)}/audit`,
  cases: (fund: string, asOf: string) => `/api/funds/${seg(fund)}/days/${seg(asOf)}/cases`,
  case: (fund: string, caseId: string) => `/api/funds/${seg(fund)}/cases/${seg(caseId)}`,
  decision: (fund: string, caseId: string) => `/api/funds/${seg(fund)}/cases/${seg(caseId)}/decision`,
};

/** Don't retry answers that will not change on a retry (signed out, forbidden, missing, refused). */
function retry(failures: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status > 0 && error.status < 500) return false;
  return failures < 2;
}

/** The app's query client; tests build theirs the same way. */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry, staleTime: 15_000, refetchOnWindowFocus: true },
      mutations: { retry: false },
    },
  });
}

export function useFunds() {
  return useQuery({
    queryKey: queryKeys.funds,
    queryFn: ({ signal }) => api.get<FundSummary[]>(paths.funds, undefined, signal),
  });
}

export function useDays(fund: string | null) {
  return useQuery({
    queryKey: queryKeys.days(fund ?? ""),
    queryFn: ({ signal }) => api.get<DaysList>(paths.days(fund ?? ""), undefined, signal),
    enabled: !!fund,
  });
}

/** The day record: status, NAV and who signed off. A 404 (no files yet) is an answer, not an error to retry. */
export function useDay(fund: string | null, asOf: string | null) {
  return useQuery({
    queryKey: queryKeys.day(fund ?? "", asOf ?? ""),
    queryFn: ({ signal }) => api.get<Day>(paths.day(fund ?? "", asOf ?? ""), undefined, signal),
    enabled: !!fund && !!asOf,
  });
}

/** The day's one release status, and whether the signed-in user could sign off. */
export function useRelease(fund: string | null, asOf: string | null) {
  return useQuery({
    queryKey: queryKeys.release(fund ?? "", asOf ?? ""),
    queryFn: ({ signal }) =>
      api.get<ReleaseForMe>(paths.release(fund ?? "", asOf ?? ""), { for_user: "me" }, signal),
    enabled: !!fund && !!asOf,
  });
}

export function useOverview(fund: string | null, asOf: string | null) {
  return useQuery({
    queryKey: queryKeys.overview(fund ?? "", asOf ?? ""),
    queryFn: ({ signal }) => api.get<Overview>(paths.overview(fund ?? "", asOf ?? ""), undefined, signal),
    enabled: !!fund && !!asOf,
  });
}

/** The day's audit trail, oldest first, and whether the whole hash chain still verifies. */
export function useDayAudit(fund: string | null, asOf: string | null) {
  return useQuery({
    queryKey: queryKeys.audit(fund ?? "", asOf ?? ""),
    queryFn: ({ signal }) => api.get<DayAudit>(paths.audit(fund ?? "", asOf ?? ""), undefined, signal),
    enabled: !!fund && !!asOf,
  });
}

/** After a decision or sign-off: refetch everything about the day, the day list and its cases. */
export async function invalidateDay(client: QueryClient, fund: string, asOf: string): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: ["funds", fund, "day", asOf] }),
    client.invalidateQueries({ queryKey: queryKeys.days(fund) }),
    client.invalidateQueries({ queryKey: ["funds", fund, "case"] }),
    client.invalidateQueries({ queryKey: queryKeys.funds }),
  ]);
}


/**
 * The case queue's filters, named as the API names them (`GET .../cases?status=&category=...`).
 * Absent means "any".
 */
export interface CaseFilters {
  status?: string;
  category?: string;
  material?: boolean;
  escalated?: boolean;
  sla?: boolean;
  age?: string;
  ai_disagrees?: boolean;
  q?: string;
}

/** The day's open cases, largest absolute NAV impact first, filtered by the server. */
export function useCases(fund: string | null, asOf: string | null, filters: CaseFilters = {}) {
  return useQuery({
    queryKey: queryKeys.cases(fund ?? "", asOf ?? "", { ...filters }),
    queryFn: ({ signal }) =>
      api.get<QueueCase[]>(paths.cases(fund ?? "", asOf ?? ""), { ...filters }, signal),
    enabled: !!fund && !!asOf,
    // Keep the last list on screen while a new filter loads, so the queue never flashes empty.
    placeholderData: keepPreviousData,
  });
}

/** One case as it stood at the end of `asOf`, with its evidence and history. */
export function useCase(fund: string | null, caseId: string | null, asOf: string | null) {
  return useQuery({
    queryKey: queryKeys.case(fund ?? "", caseId ?? "", asOf ?? undefined),
    queryFn: ({ signal }) =>
      api.get<CaseDetail>(paths.case(fund ?? "", caseId ?? ""), { as_of: asOf }, signal),
    enabled: !!fund && !!caseId && !!asOf,
  });
}

/**
 * Approve, reject or reclassify a case. On success the answer (the updated case) replaces
 * the cached case and everything about the day is refetched, so the strip, the queue and
 * the overview agree. On a refusal (409: someone else decided first, the day is locked)
 * the day is refetched too, so the screen shows what is true now.
 */
export function useDecision(fund: string, asOf: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ caseId, request }: { caseId: string; request: DecisionRequest }) =>
      api.post<CaseDetail>(paths.decision(fund, caseId), request),
    onSuccess: async (detail, { caseId }) => {
      client.setQueryData(queryKeys.case(fund, caseId, asOf), detail);
      await invalidateDay(client, fund, asOf);
    },
    onError: async () => {
      await invalidateDay(client, fund, asOf);
    },
  });
}

/**
 * Sign off the day's NAV (approvers only). The answer is the signed-off day; it replaces
 * the cached day and everything about the day is refetched (the strip, the release, the
 * day list with the next business day, the audit trail). A refusal (409 with reasons, or
 * 403 for a role that may not sign off) refetches the day too, so the screen shows what
 * is true now.
 */
export function useSignOff(fund: string, asOf: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Day>(paths.signoff(fund, asOf)),
    onSuccess: async (day) => {
      client.setQueryData(queryKeys.day(fund, asOf), day);
      await invalidateDay(client, fund, asOf);
    },
    onError: async () => {
      await invalidateDay(client, fund, asOf);
    },
  });
}
