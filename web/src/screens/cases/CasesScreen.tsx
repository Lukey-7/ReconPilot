/**
 * The case workbench (spec section 10, screen 3): three panes that stay put, the queue, the
 * open case and its evidence, with the decision bar always in reach.
 *
 * The fund, the day, the open case (`case`) and the queue's filters live in the address, so
 * a link from the overview opens the right case and a filtered queue can be shared. Every
 * figure comes from the API: the queue from `GET .../cases` (filtered by the server), the
 * case and its evidence from `GET .../cases/{id}?as_of=`.
 *
 * Keys: j/k or the arrows move the cursor in the queue, Enter opens the case under it, a, r
 * and c decide (the first press on a row that is not open opens it instead), / searches.
 */
import "./cases.css";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { type CaseFilters, useCase, useCases, useDay } from "../../api/queries";
import { useUser } from "../../auth/AuthContext";
import { Empty, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { count } from "../../format";
import { useShortcut } from "../../keyboard/KeyboardProvider";
import { useWorkspace } from "../../shell/workspace";
import { ScreenContext } from "../ScreenContext";
import { CasePane } from "./CasePane";
import { EvidencePane, type EvidenceMode } from "./EvidencePane";
import { filtersFrom, withFilter, withoutFilters } from "./filters";
import { QueuePane } from "./QueuePane";

const EVIDENCE_KEY = "rp-evidence-pane";
const INTERACTIVE = 'a[href], button, summary, input, select, textarea, [role="button"], [role="tab"], [role="link"]';

function storedMode(): EvidenceMode {
  try {
    const value = window.localStorage.getItem(EVIDENCE_KEY);
    return value === "wide" || value === "collapsed" ? value : "normal";
  } catch {
    return "normal";
  }
}

function storeMode(mode: EvidenceMode): void {
  try {
    window.localStorage.setItem(EVIDENCE_KEY, mode);
  } catch {
    /* storage blocked: the choice lasts until the page is left */
  }
}

/** Whether a key press belongs to the focused control (a button's Enter, a tab's arrows). */
function onControl(event: KeyboardEvent): boolean {
  return event.target instanceof Element && event.target.closest(INTERACTIVE) != null;
}

/** Why the queue cannot be shown for this day, in plain words, or null. */
function notReadyText(error: unknown): string | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 404) return `${error.message} Upload the day's files, then run the day to see its cases.`;
  if (error.status === 409) return `${error.message} Run the day to see its cases.`;
  return null;
}

/** The panes fill the window below the strip and scroll inside, so they stay put. */
function useFillHeight() {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      el.style.setProperty("--wb-top", `${Math.max(0, Math.round(top))}px`);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  return ref;
}

function Workbench({ fund, currency, asOf }: { fund: string; currency: string; asOf: string }) {
  const user = useUser();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => filtersFrom(params), [params]);
  const openId = params.get("case");

  const queue = useCases(fund, asOf, filters);
  const detail = useCase(fund, openId, asOf);
  const day = useDay(fund, asOf);

  const [order, setOrder] = useState<string[]>([]);
  const [cursorId, setCursorId] = useState<string | null>(null);
  const lastIndex = useRef(0);
  const [announcement, setAnnouncement] = useState("");
  const [mode, setModeState] = useState<EvidenceMode>(storedMode);
  const searchRef = useRef<HTMLInputElement>(null);
  const tableRef = useRef<HTMLDivElement>(null);
  const fillRef = useFillHeight();

  const setMode = useCallback((next: EvidenceMode) => {
    setModeState(next);
    storeMode(next);
  }, []);

  const announce = useCallback((message: string) => setAnnouncement(message), []);

  const setFilter = useCallback(
    (key: keyof CaseFilters, value: string | boolean | undefined) =>
      setParams((prev) => withFilter(prev, key, value), { replace: true }),
    [setParams],
  );
  const clearFilters = useCallback(() => setParams((prev) => withoutFilters(prev), { replace: true }), [setParams]);

  const open = useCallback(
    (caseId: string) => {
      setCursorId(caseId);
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("case", caseId);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // With no case chosen, open the first in the queue (the largest impact), as a desk would.
  const first = !queue.isPlaceholderData ? queue.data?.[0]?.case_id : undefined;
  useEffect(() => {
    if (!openId && first) open(first);
  }, [openId, first, open]);

  const rowElement = (caseId: string): HTMLElement | undefined =>
    Array.from(tableRef.current?.querySelectorAll<HTMLElement>("tr[data-row-id]") ?? []).find(
      (row) => row.dataset.rowId === caseId,
    );

  const move = (delta: 1 | -1) => {
    if (!order.length) return;
    const from = cursorId ?? openId;
    const at = from ? order.indexOf(from) : -1;
    let next: number;
    if (at >= 0) next = at + delta;
    else next = delta > 0 ? lastIndex.current : lastIndex.current - 1; // the row it was on has left the list
    next = Math.max(0, Math.min(order.length - 1, next));
    lastIndex.current = next;
    const id = order[next];
    if (!id) return;
    setCursorId(id);
    const row = rowElement(id);
    row?.focus();
    row?.scrollIntoView?.({ block: "nearest" });
  };

  useEffect(() => {
    const at = cursorId ? order.indexOf(cursorId) : -1;
    if (at >= 0) lastIndex.current = at;
  }, [cursorId, order]);

  // A case opened from elsewhere (the palette, a link, the address) brings the cursor with it,
  // so a, r and c then decide the case in view rather than reopening the row the cursor was on.
  useEffect(() => {
    if (openId) setCursorId(openId);
  }, [openId]);

  const group = "Cases";
  useShortcut("j", () => move(1), { description: "Next case in the queue", group });
  useShortcut("k", () => move(-1), { description: "Previous case in the queue", group });
  useShortcut("ArrowDown", () => move(1), { description: "Next case in the queue", group, when: (e) => !onControl(e) });
  useShortcut("ArrowUp", () => move(-1), { description: "Previous case in the queue", group, when: (e) => !onControl(e) });
  useShortcut(
    "Enter",
    () => {
      if (cursorId) open(cursorId);
    },
    { description: "Open the case under the cursor", group, when: (e) => !onControl(e) && !!cursorId },
  );
  useShortcut(
    "/",
    () => {
      searchRef.current?.focus();
      searchRef.current?.select();
    },
    { description: "Search the queue", group, palette: true },
  );

  /** a, r and c on a row that is not the open case open it first, so a key never decides a case you cannot see. */
  const beforeShortcut = useCallback(() => {
    if (cursorId && cursorId !== openId && order.includes(cursorId)) {
      open(cursorId);
      announce(`Opened ${cursorId}. Press the key again to decide it.`);
      return true;
    }
    return false;
  }, [cursorId, openId, order, open, announce]);

  const at = openId ? order.indexOf(openId) : -1;
  const position = !openId
    ? ""
    : at >= 0
      ? `${count(at + 1)} of ${count(order.length)} in the queue`
      : queue.data
        ? "Not in the queue as filtered"
        : "";

  const notReady = notReadyText(queue.error);
  const nothingOpen = notReady
    ? "No cases to show for this day."
    : queue.data && queue.data.length === 0
      ? "No case to open."
      : "Pick a case from the queue.";

  return (
    <>
      <div ref={fillRef} className={`wb wb-ev-${mode}`}>
        <QueuePane
          cases={queue.data}
          loading={queue.isPending}
          fetching={queue.isFetching}
          error={notReady ? null : queue.error}
          retry={() => void queue.refetch()}
          notReady={notReady}
          filters={filters}
          setFilter={setFilter}
          clearFilters={clearFilters}
          openId={openId}
          onOpen={open}
          onOrderChange={setOrder}
          searchRef={searchRef}
          tableRef={tableRef}
          onRowFocus={setCursorId}
        />
        <CasePane
          detail={detail.data}
          loading={!!openId && detail.isPending}
          error={detail.error}
          retry={() => void detail.refetch()}
          position={position}
          fund={fund}
          asOf={asOf}
          role={user.role}
          signedOffBy={day.data?.signed_off_by ?? null}
          beforeShortcut={beforeShortcut}
          nothingOpen={nothingOpen}
          currency={currency}
        />
        <EvidencePane detail={detail.data} currency={currency} mode={mode} setMode={setMode} />
      </div>
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
    </>
  );
}

export function CasesScreen() {
  const { fund, asOf, fundsLoading, daysLoading } = useWorkspace();

  let body;
  if (!fund) body = fundsLoading ? <Loading label="Loading funds" /> : <Empty>No fund is set up yet.</Empty>;
  else if (!asOf)
    body = daysLoading ? (
      <Loading label="Loading business days" />
    ) : (
      <Empty>No business day has been loaded for {fund.name} yet. Upload the first day&rsquo;s files to begin.</Empty>
    );
  else body = <Workbench key={`${fund.code}|${asOf}`} fund={fund.code} currency={fund.base_currency} asOf={asOf} />;

  return (
    <section className="screen wb-screen">
      <ScreenHeader title="Cases">
        <ScreenContext />
      </ScreenHeader>
      {body}
    </section>
  );
}
