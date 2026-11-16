/**
 * The command palette (Ctrl+K): one field over one list, to jump to a case, a screen, a
 * fund or a business day, or to run an action the person may run now.
 *
 * Actions come from the keyboard registry (`useCommand`, and shortcuts registered with
 * `palette`), which holds only what the role and the day's state allow; the server still
 * checks every request. Cases come from the day's queue (`GET .../cases`, the same query
 * the workbench uses), so every figure is the server's. A case id typed in full that is not
 * in the day's queue (one that cleared earlier, say) is looked up on the last day it was in
 * a run (`GET .../cases/{id}`) and opens on that day. Typing narrows every group: each
 * word must appear in an item's name or details. Arrows move, Enter runs, Esc closes. The
 * action runs once the dialog has closed, so focus lands where the action puts it.
 */
import * as Dialog from "@radix-ui/react-dialog";
import { type KeyboardEvent, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { ApiError } from "../api/client";
import { useCaseLatest, useCases } from "../api/queries";
import type { CaseDetail, QueueCase } from "../api/types";
import { Icon } from "../components/Icon";
import { Kbd } from "../components/Kbd";
import { useReturnFocus } from "../components/returnFocus";
import { dayLabel, money, plural } from "../format";
import { type CommandInfo, useCommands } from "../keyboard/KeyboardProvider";
import { causeLabel, dayStatusLabel, statusLabel } from "../vocabulary";
import { FUNDS_SCREEN, SCREENS } from "./TopBar";
import { useWorkspace } from "./workspace";

export interface PaletteItem {
  id: string;
  group: string;
  label: string;
  detail?: string;
  keys?: string;
  /** Lower-case text the query is matched against. */
  text: string;
  current?: boolean;
  run: () => void;
}

/** The groups in the order they are shown, and how many of each show with and without a query. */
export const PALETTE_GROUPS = [
  { name: "Actions", idle: 12, matching: 8 },
  { name: "Screens", idle: 7, matching: 7 },
  { name: "Cases", idle: 5, matching: 10 },
  { name: "Funds", idle: 6, matching: 8 },
  { name: "Business days", idle: 5, matching: 8 },
] as const;

/** Every word of the query must appear somewhere in the item's text. */
export function matches(item: Pick<PaletteItem, "text">, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return words.every((w) => item.text.includes(w));
}

/** The note under a capped group: how many more items match. */
export function moreText(n: number): string {
  return `${plural(n, "more matches", "more match")}; keep typing`;
}

const CASE_ID = /^ex-\d{8}-\d+$/i;

/** The case id the query names in full, if it names one that is not among the listed items. */
export function caseIdToLookUp(query: string, items: Pick<PaletteItem, "id">[]): string | null {
  const q = query.trim();
  if (!CASE_ID.test(q)) return null;
  const id = q.toUpperCase();
  return items.some((i) => i.id === `case-${id}`) ? null : id;
}

/** A case from outside the day's queue, opening on the last day it was in a run. */
function lookedUpItem(c: CaseDetail, open: (id: string, day: string) => void): PaletteItem {
  const base = caseItem(c, () => {});
  const when = c.is_open ? `open on ${dayLabel(c.as_of)}` : `cleared ${dayLabel(c.as_of)}`;
  return { ...base, id: `lookup-${c.case_id}`, detail: `${base.detail} · ${when}`, run: () => open(c.case_id, c.as_of) };
}

function textOf(...parts: (string | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ").toLowerCase();
}

/** Screen actions first (they are what the person came to the screen for), then the shell's. */
function orderedActions(commands: CommandInfo[]): CommandInfo[] {
  return [...commands.filter((c) => c.group !== "General"), ...commands.filter((c) => c.group === "General")];
}

function caseItem(c: QueueCase, open: (id: string) => void): PaletteItem {
  const cause = causeLabel(c.final_category ?? c.category);
  const status = statusLabel(c.status);
  return {
    id: `case-${c.case_id}`,
    group: "Cases",
    label: c.case_id,
    detail: `${c.security_name || c.security_id} · ${cause} · ${money(c.nav_impact, { signed: true })} · ${status}`,
    text: textOf(c.case_id, c.security_id, c.security_name, cause, status, c.material ? "material" : null, c.escalated ? "escalated" : null),
    run: () => open(c.case_id),
  };
}

function useItems(close: (run: () => void) => void): PaletteItem[] {
  const navigate = useNavigate();
  const { fund, funds, days, asOf, href, setFund, setDay } = useWorkspace();
  const commands = useCommands();
  const cases = useCases(fund?.code ?? null, asOf);

  return useMemo(() => {
    const items: PaletteItem[] = [];
    for (const c of orderedActions(commands)) {
      items.push({
        id: `action-${c.id}`,
        group: "Actions",
        label: c.label,
        detail: c.group === "General" ? undefined : c.group,
        keys: c.keys,
        text: textOf(c.label, c.group, c.keywords),
        run: () => close(c.run),
      });
    }
    for (const s of [...SCREENS, FUNDS_SCREEN]) {
      items.push({
        id: `screen-${s.path}`,
        group: "Screens",
        label: s.label,
        keys: s.keys,
        text: textOf(s.label, "go to screen", s.path.slice(1)),
        run: () => close(() => navigate(href(s.path))),
      });
    }
    for (const c of cases.data ?? []) items.push(caseItem(c, (id) => close(() => navigate(href("/cases", { case: id })))));
    for (const f of funds) {
      items.push({
        id: `fund-${f.code}`,
        group: "Funds",
        label: `${f.code} · ${f.name}`,
        detail: f.code === fund?.code ? "Working now" : f.latest_day ? `Latest day ${dayLabel(f.latest_day)}` : "No days yet",
        current: f.code === fund?.code,
        text: textOf(f.code, f.name, "fund"),
        run: () => close(() => setFund(f.code)),
      });
    }
    const dayRows: { as_of: string; status: string | null }[] = (days?.days ?? []).map((d) => ({ as_of: d.as_of, status: d.status }));
    const nextDay = days?.next_day;
    if (nextDay && !dayRows.some((d) => d.as_of === nextDay)) dayRows.unshift({ as_of: nextDay, status: null });
    for (const d of dayRows) {
      const status = dayStatusLabel(d.status);
      items.push({
        id: `day-${d.as_of}`,
        group: "Business days",
        label: dayLabel(d.as_of),
        detail: d.as_of === asOf ? `${status} · showing now` : status,
        current: d.as_of === asOf,
        text: textOf(dayLabel(d.as_of), d.as_of, status, "day"),
        run: () => close(() => setDay(d.as_of)),
      });
    }
    return items;
  }, [commands, cases.data, funds, fund, days, asOf, href, navigate, setFund, setDay, close]);
}

/** The items to show for a query, grouped in order and capped per group. */
export function visibleGroups(items: PaletteItem[], query: string): { name: string; items: PaletteItem[]; more: number }[] {
  const q = query.trim();
  return PALETTE_GROUPS.map((g) => {
    const all = items.filter((i) => i.group === g.name && (!q || matches(i, q)));
    const cap = q ? g.matching : g.idle;
    return { name: g.name, items: all.slice(0, cap), more: Math.max(0, all.length - cap) };
  }).filter((g) => g.items.length > 0);
}

function PaletteBody({ close, dismiss }: { close: (run: () => void) => void; dismiss: () => void }) {
  const listed = useItems(close);
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  const { fund, href } = useWorkspace();
  const lookupId = caseIdToLookUp(query, listed);
  const lookup = useCaseLatest(fund?.code ?? null, lookupId);
  const found = lookupId && lookup.data?.case_id === lookupId ? lookup.data : null;
  const items = useMemo(
    () =>
      found
        ? [...listed, lookedUpItem(found, (id, day) => close(() => navigate(href("/cases", { case: id, day }))))]
        : listed,
    [listed, found, close, navigate, href],
  );
  const lookupNote =
    !lookupId || found
      ? null
      : lookup.isPending
        ? `Looking up ${lookupId}…`
        : lookup.error instanceof ApiError && lookup.error.status === 404
          ? `No case ${lookupId} in ${fund?.code ?? "this fund"}.`
          : `${lookupId} could not be looked up just now.`;
  const [active, setActive] = useState(0);
  const ids = useId();
  const listId = `${ids}-list`;

  const groups = useMemo(() => visibleGroups(items, query), [items, query]);
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const at = Math.min(active, Math.max(0, flat.length - 1));
  const current = flat[at];
  const optionId = (item: PaletteItem) => `${ids}-${item.id}`;

  useEffect(() => {
    if (current) document.getElementById(`${ids}-${current.id}`)?.scrollIntoView?.({ block: "nearest" });
  }, [current, ids]);

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault(); // Ctrl+K again closes the palette
      dismiss();
      return;
    }
    if (!flat.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((at + step + flat.length) % flat.length);
    } else if (event.key === "Home" && event.ctrlKey) {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End" && event.ctrlKey) {
      event.preventDefault();
      setActive(flat.length - 1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      current?.run();
    }
  };

  let position = 0;
  return (
    <>
      <div className="pal-field">
        <Icon name="search" />
        <input
          className="pal-input"
          role="combobox"
          aria-label="Jump to a case, screen, fund or day, or run an action"
          aria-expanded="true"
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={current ? optionId(current) : undefined}
          placeholder="Jump to a case, screen, fund or day, or run an action"
          autoComplete="off"
          spellCheck={false}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
      </div>
      <div className="pal-list" id={listId} role="listbox" aria-label="Results">
        {groups.map((g) => (
          <div key={g.name} role="group" aria-labelledby={`${ids}-g-${g.name}`} className="pal-group">
            <div className="pal-group-name" id={`${ids}-g-${g.name}`} role="presentation">
              {g.name}
              {g.more > 0 && <span className="faint"> · {moreText(g.more)}</span>}
            </div>
            {g.items.map((item) => {
              const index = position++;
              const selected = index === at;
              return (
                <div
                  key={item.id}
                  id={optionId(item)}
                  role="option"
                  aria-selected={selected}
                  aria-current={item.current || undefined}
                  className={`pal-option${selected ? " active" : ""}`}
                  // Options are reached through the field (aria-activedescendant); a click
                  // must not take focus from it.
                  tabIndex={-1}
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseMove={() => {
                    if (!selected) setActive(index);
                  }}
                  onClick={() => item.run()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") item.run();
                  }}
                >
                  <span className="pal-label">{item.label}</span>
                  {item.detail && <span className="pal-detail">{item.detail}</span>}
                  {item.keys && <Kbd keys={item.keys} />}
                </div>
              );
            })}
          </div>
        ))}
        {!flat.length && (
          <p className="pal-empty muted">{lookupNote ?? <>Nothing matches &ldquo;{query.trim()}&rdquo;.</>}</p>
        )}
      </div>
      <p className="sr-only" role="status" aria-live="polite">
        {query.trim() ? plural(flat.length, "result") : ""}
      </p>
      <p className="pal-foot faint" aria-hidden="true">
        <span>
          <kbd>↑</kbd>
          <kbd>↓</kbd> move
        </span>
        <span>
          <kbd>Enter</kbd> go
        </span>
        <span>
          <kbd>Esc</kbd> close
        </span>
      </p>
    </>
  );
}

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const pending = useRef<(() => void) | null>(null);
  const returnFocus = useReturnFocus(open);
  const close = useCallback(
    (run: () => void) => {
      pending.current = run;
      onOpenChange(false);
    },
    [onOpenChange],
  );
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content
          className="dialog palette"
          onCloseAutoFocus={(event) => {
            const run = pending.current;
            pending.current = null;
            if (run) {
              event.preventDefault(); // the action decides where focus goes
              run();
            }
            returnFocus(event); // closed without an action: focus goes back where it was
          }}
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <Dialog.Description className="sr-only">
            Type to find a case, a screen, a fund, a business day or an action. Arrow keys move, Enter goes, Escape closes.
          </Dialog.Description>
          <PaletteBody close={close} dismiss={() => onOpenChange(false)} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
