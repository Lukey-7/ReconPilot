/**
 * The fund and business day being worked, held in the URL (`?fund=GEF1&day=2026-11-13`)
 * so every screen, link and reload agrees on them and a link can be shared.
 *
 * With nothing in the URL the last fund used (remembered in this browser) or the first
 * fund is chosen, and its latest loaded day. The choice is written back into the URL.
 */
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router";

import { useDays, useFunds } from "../api/queries";
import type { DaysList, FundSummary } from "../api/types";

const FUND_STORAGE_KEY = "rp-fund";
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

function rememberedFund(): string | null {
  try {
    return window.localStorage.getItem(FUND_STORAGE_KEY);
  } catch {
    return null;
  }
}

function rememberFund(code: string): void {
  try {
    window.localStorage.setItem(FUND_STORAGE_KEY, code);
  } catch {
    /* storage blocked: the URL still carries the choice */
  }
}

export interface WorkspaceValue {
  funds: FundSummary[];
  fundsLoading: boolean;
  fundsError: unknown;
  fund: FundSummary | null;
  days: DaysList | undefined;
  daysLoading: boolean;
  /** The business day being worked (ISO date), or null when the fund has no days yet. */
  asOf: string | null;
  setFund: (code: string) => void;
  setDay: (asOf: string) => void;
  /** A link to another screen keeping the fund and day. */
  href: (path: string, extra?: Record<string, string>) => string;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const fundsQuery = useFunds();
  const funds = useMemo(() => fundsQuery.data ?? [], [fundsQuery.data]);

  const wantedFund = params.get("fund")?.toUpperCase() ?? null;
  const fund = useMemo(() => {
    if (!funds.length) return null;
    const byCode = (code: string | null) => (code ? funds.find((f) => f.code === code) : undefined);
    return byCode(wantedFund) ?? byCode(rememberedFund()) ?? funds[0] ?? null;
  }, [funds, wantedFund]);

  const daysQuery = useDays(fund?.code ?? null);
  const wantedDay = params.get("day");
  const asOf = wantedDay && ISO_DAY.test(wantedDay) ? wantedDay : (daysQuery.data?.latest_day ?? null);

  // Write the resolved choice into the URL, so a reload or a shared link shows the same day.
  useEffect(() => {
    if (!fund) return;
    const next = new URLSearchParams(params);
    let changed = false;
    if (params.get("fund") !== fund.code) {
      next.set("fund", fund.code);
      changed = true;
    }
    if (asOf && params.get("day") !== asOf) {
      next.set("day", asOf);
      changed = true;
    }
    if (changed) setParams(next, { replace: true });
  }, [fund, asOf, params, setParams]);

  useEffect(() => {
    if (fund) rememberFund(fund.code);
  }, [fund]);

  const setFund = useCallback(
    (code: string) => {
      const next = new URLSearchParams(params);
      next.set("fund", code);
      next.delete("day"); // the new fund's latest day
      setParams(next);
    },
    [params, setParams],
  );

  const setDay = useCallback(
    (day: string) => {
      const next = new URLSearchParams(params);
      next.set("day", day);
      setParams(next);
    },
    [params, setParams],
  );

  const href = useCallback(
    (path: string, extra: Record<string, string> = {}) => {
      const next = new URLSearchParams();
      if (fund) next.set("fund", fund.code);
      if (asOf) next.set("day", asOf);
      for (const [key, value] of Object.entries(extra)) next.set(key, value);
      const qs = next.toString();
      return qs ? `${path}?${qs}` : path;
    },
    [fund, asOf],
  );

  const value = useMemo<WorkspaceValue>(
    () => ({
      funds,
      fundsLoading: fundsQuery.isPending,
      fundsError: fundsQuery.error,
      fund,
      days: daysQuery.data,
      daysLoading: daysQuery.isPending && !!fund,
      asOf,
      setFund,
      setDay,
      href,
    }),
    [funds, fundsQuery.isPending, fundsQuery.error, fund, daysQuery.data, daysQuery.isPending, asOf, setFund, setDay, href],
  );
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace needs a WorkspaceProvider");
  return value;
}
