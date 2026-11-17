/**
 * The administration API (`/api/admin/...`) and the unlock API
 * (`/api/funds/{code}/days/{as_of}/unlock`): their types, queries and mutations.
 *
 * Kept beside the admin screens rather than in `api/queries.ts`: only these screens and
 * the sign-off screen's unlock panel use them. Every call goes through the one client
 * (`apiFetch`), so the session cookie, CSRF header and 401 handling are the same as
 * everywhere else. Every control is enforced on the server; the flags here (`*_by_me`)
 * only decide which buttons are offered.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, apiFetch, seg } from "../../api/client";
import { invalidateDay, queryKeys as appKeys } from "../../api/queries";
import type { FundDetail, FundSummary, RoleName } from "../../api/types";

// --------------------------------------------------------------------------- types

/** `GET /api/admin/users`: one real user as an administrator sees them. */
export interface AdminUser {
  username: string;
  display_name: string;
  role: RoleName;
  is_admin: boolean;
  is_active: boolean;
  locked: boolean;
  locked_until: string | null;
  failed_logins: number;
  last_login_at: string | null;
  created_at: string | null;
  /** Sessions that could still be used: signed in somewhere now. */
  live_sessions: number;
}

export interface NewUser {
  username: string;
  display_name: string;
  password: string;
  role: RoleName;
  is_admin: boolean;
}

export interface UserChange {
  display_name?: string;
  role?: RoleName;
  is_admin?: boolean;
  is_active?: boolean;
}

/** One AI provider as the server has it: never its key. */
export interface AiProvider {
  provider: string;
  label: string;
  configured: boolean;
  model: string | null;
  /** True for the private, OpenAI-compatible endpoint (evidence goes to `endpoint`, not a public provider). */
  private: boolean;
  endpoint: string | null;
  problem: string | null;
}

export interface AiProviders {
  /** The provider a fund with no choice of its own uses, or null when the server has none. */
  default: string | null;
  providers: AiProvider[];
}

/** A fund's AI switch. */
export interface AiState {
  enabled: boolean;
  /** The fund's own choice; null means the server's default. */
  provider: string | null;
  effective_provider: string | null;
  model: string | null;
}

/** `GET /api/admin/funds/{code}`: the fund's detail and its AI switch. */
export interface AdminFund extends FundDetail {
  ai: AiState;
}

export interface NewFund {
  code: string;
  name: string;
  start_date: string;
  non_business_dates: string[];
  settings: Record<string, unknown>;
}

export interface FundChange {
  name?: string;
  settings?: Record<string, unknown>;
  non_business_dates?: string[];
}

export interface AiSwitch {
  enabled: boolean;
  provider: string | null;
  acknowledged: boolean;
}

export type UnlockStatus = "pending" | "confirmed" | "declined" | "withdrawn" | "expired";

export interface UnlockRequest {
  id: number;
  status: UnlockStatus;
  reason: string;
  requested_by: string | null;
  requested_at: string;
  expires_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string;
  confirmable_by_me: boolean;
  declinable_by_me: boolean;
  withdrawable_by_me: boolean;
}

/** `GET /api/funds/{code}/days/{as_of}/unlock`. */
export interface UnlockState {
  fund: string;
  as_of: string;
  day_status: string;
  signed_off_by: string | null;
  signed_off_at: string | null;
  unlockable: boolean;
  /** Why the day cannot be unlocked now, in the server's words. */
  problem: string | null;
  requestable_by_me: boolean;
  pending: UnlockRequest | null;
  history: UnlockRequest[];
  confirm_within_hours: number;
}

// --------------------------------------------------------------------------- paths and keys

export const adminPaths = {
  users: "/api/admin/users",
  user: (username: string) => `/api/admin/users/${seg(username)}`,
  password: (username: string) => `/api/admin/users/${seg(username)}/password`,
  unlockAccount: (username: string) => `/api/admin/users/${seg(username)}/unlock`,
  providers: "/api/admin/ai/providers",
  funds: "/api/admin/funds",
  fund: (code: string) => `/api/admin/funds/${seg(code)}`,
  ai: (code: string) => `/api/admin/funds/${seg(code)}/ai`,
  unlock: (fund: string, asOf: string) => `/api/funds/${seg(fund)}/days/${seg(asOf)}/unlock`,
  unlockConfirm: (fund: string, asOf: string, id: number) =>
    `/api/funds/${seg(fund)}/days/${seg(asOf)}/unlock/${id}/confirm`,
  unlockDecline: (fund: string, asOf: string, id: number) =>
    `/api/funds/${seg(fund)}/days/${seg(asOf)}/unlock/${id}/decline`,
};

export const adminKeys = {
  users: ["admin", "users"] as const,
  providers: ["admin", "providers"] as const,
  fund: (code: string) => ["admin", "fund", code] as const,
  unlock: (fund: string, asOf: string) => ["funds", fund, "day", asOf, "unlock"] as const,
};

const patch = <T>(path: string, json: unknown) => apiFetch<T>(path, { method: "PATCH", json });

// --------------------------------------------------------------------------- users

export function useAdminUsers() {
  return useQuery({
    queryKey: adminKeys.users,
    queryFn: ({ signal }) => api.get<AdminUser[]>(adminPaths.users, undefined, signal),
  });
}

/** A mutation that refreshes the user list afterwards. */
function useUserMutation<V>(fn: (vars: V) => Promise<AdminUser>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => void client.invalidateQueries({ queryKey: adminKeys.users }),
  });
}

export function useCreateUser() {
  return useUserMutation((user: NewUser) => api.post<AdminUser>(adminPaths.users, user));
}

export function useChangeUser() {
  return useUserMutation(({ username, change }: { username: string; change: UserChange }) =>
    patch<AdminUser>(adminPaths.user(username), change),
  );
}

export function useResetPassword() {
  return useUserMutation(({ username, password }: { username: string; password: string }) =>
    api.post<AdminUser>(adminPaths.password(username), { password }),
  );
}

export function useUnlockAccount() {
  return useUserMutation((username: string) => api.post<AdminUser>(adminPaths.unlockAccount(username)));
}

// --------------------------------------------------------------------------- funds and AI

export function useAiProviders() {
  return useQuery({
    queryKey: adminKeys.providers,
    queryFn: ({ signal }) => api.get<AiProviders>(adminPaths.providers, undefined, signal),
  });
}

export function useAdminFund(code: string | null) {
  return useQuery({
    queryKey: adminKeys.fund(code ?? ""),
    queryFn: ({ signal }) => api.get<AdminFund>(adminPaths.fund(code ?? ""), undefined, signal),
    enabled: !!code,
  });
}

/** After a fund changes: its admin view, its public detail (the Funds screen) and the fund list. */
function useFundMutation<V>(fn: (vars: V) => Promise<AdminFund>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (fund) => {
      client.setQueryData(adminKeys.fund(fund.code), fund);
      void client.invalidateQueries({ queryKey: appKeys.fund(fund.code) });
      void client.invalidateQueries({ queryKey: appKeys.funds, exact: true });
    },
  });
}

/**
 * Create a fund. The new fund is put into the cached fund list at once, so a caller that
 * switches to it finds it there (otherwise the workspace, not finding it, would fall back
 * to another fund); the list is then read again from the server.
 */
export function useCreateFund() {
  const client = useQueryClient();
  return useFundMutation(async (fund: NewFund) => {
    const created = await api.post<AdminFund>(adminPaths.funds, fund);
    const summary: FundSummary = {
      code: created.code,
      name: created.name,
      base_currency: created.base_currency,
      start_date: created.start_date,
      latest_day: created.latest_day,
      latest_status: created.latest_status,
    };
    client.setQueryData<FundSummary[]>(appKeys.funds, (old) =>
      [...(old ?? []).filter((f) => f.code !== summary.code), summary].sort((x, y) => x.code.localeCompare(y.code)),
    );
    return created;
  });
}

export function useChangeFund(code: string) {
  return useFundMutation((change: FundChange) => patch<AdminFund>(adminPaths.fund(code), change));
}

export function useSwitchAi(code: string) {
  return useFundMutation((change: AiSwitch) => api.put<AdminFund>(adminPaths.ai(code), change));
}

// --------------------------------------------------------------------------- unlocking a day

export function useUnlock(fund: string | null, asOf: string | null, enabled = true) {
  return useQuery({
    queryKey: adminKeys.unlock(fund ?? "", asOf ?? ""),
    queryFn: ({ signal }) => api.get<UnlockState>(adminPaths.unlock(fund ?? "", asOf ?? ""), undefined, signal),
    enabled: enabled && !!fund && !!asOf,
  });
}

/** An unlock step; afterwards the day itself is read again, so every screen moves with it. */
function useUnlockMutation<V>(fund: string, asOf: string, fn: (vars: V) => Promise<UnlockState>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async (state) => {
      client.setQueryData(adminKeys.unlock(fund, asOf), state);
      await invalidateDay(client, fund, asOf);
    },
  });
}

export function useAskUnlock(fund: string, asOf: string) {
  return useUnlockMutation(fund, asOf, (reason: string) =>
    api.post<UnlockState>(adminPaths.unlock(fund, asOf), { reason }),
  );
}

export function useConfirmUnlock(fund: string, asOf: string) {
  return useUnlockMutation(fund, asOf, ({ id, note }: { id: number; note: string }) =>
    api.post<UnlockState>(adminPaths.unlockConfirm(fund, asOf, id), { note }),
  );
}

export function useDeclineUnlock(fund: string, asOf: string) {
  return useUnlockMutation(fund, asOf, ({ id, note }: { id: number; note: string }) =>
    api.post<UnlockState>(adminPaths.unlockDecline(fund, asOf, id), { note }),
  );
}
