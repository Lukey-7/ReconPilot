/**
 * The top bar: screens, the fund and business day being worked, the way into the command
 * palette, the signed-in user and their role, the theme and the shortcuts. Nothing
 * decorative: each screen's shortcut is in its tooltip, the help dialog and the palette,
 * not printed beside every link.
 *
 * Paper's glass bar, in two rows: the brand, the screens in a glass capsule (the current
 * one under a gradient-tinted lens that springs between items; below 768px the capsule
 * floats at the bottom of the window instead) and the theme, shortcuts and user; then the
 * fund and day being worked, with search and the demo's role beside them.
 */
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useLayoutEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";

import { useRelease } from "../api/queries";
import { useAuth, useUser } from "../auth/AuthContext";
import { Icon, type IconName } from "../components/Icon";
import { Kbd } from "../components/Kbd";
import { RoleSwitcher } from "../demo/RoleSwitcher";
import { count, dayLabel } from "../format";
import { useCommand } from "../keyboard/KeyboardProvider";
import { ThemeToggle } from "../theme/ThemeProvider";
import { dayStatusLabel, roleLabel } from "../vocabulary";
import { useWorkspace } from "./workspace";

export const SCREENS = [
  { path: "/overview", label: "Overview", keys: "g o" },
  { path: "/upload", label: "Upload", keys: "g u" },
  { path: "/cases", label: "Cases", keys: "g q" },
  { path: "/signoff", label: "Sign-off", keys: "g s" },
  { path: "/mi", label: "MI", keys: "g m" },
  { path: "/audit", label: "Audit log", keys: "g l" },
] as const;

const SCREEN_ICONS: Record<(typeof SCREENS)[number]["path"], IconName> = {
  "/overview": "overview",
  "/upload": "upload",
  "/cases": "cases",
  "/signoff": "signoff",
  "/mi": "mi",
  "/audit": "audit",
};

/** "g o" as "G then O", for a tooltip. */
export function keysTitle(keys: string): string {
  return keys
    .split(" ")
    .map((k) => k.toUpperCase())
    .join(" then ");
}

/** Users and funds administration: reached from the user menu and the palette, by administrators only. */
export const ADMIN_SCREEN = { path: "/admin/users", label: "Administration" } as const;

/** Every fund and the chosen fund's settings: reached from beside the fund selector, not the screen list. */
export const FUNDS_SCREEN = { path: "/funds", label: "Funds", keys: "g f" } as const;

function PendingBadge() {
  const { fund, asOf } = useWorkspace();
  const release = useRelease(fund?.code ?? null, asOf);
  const pending = release.data?.reasons.find((r) => r.code === "PENDING_DECISIONS")?.case_ids.length ?? 0;
  if (!pending) return null;
  return (
    <span className="badge count-pill" title={`${pending} pending a decision`}>
      {count(pending)}
      <span className="sr-only"> pending a decision</span>
    </span>
  );
}

/**
 * The screens in a glass capsule. The lens is one element behind the links that moves to
 * the current one (measured after layout), so it springs from item to item; with no
 * current screen (funds, administration) it fades out.
 */
function Screens() {
  const { href } = useWorkspace();
  const { pathname } = useLocation();
  const listRef = useRef<HTMLDivElement>(null);
  const [lens, setLens] = useState<{ x: number; w: number } | null>(null);
  const current = SCREENS.findIndex((s) => pathname === s.path || pathname.startsWith(`${s.path}/`));

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const measure = () => {
      const link = current >= 0 ? list.querySelectorAll<HTMLElement>("a")[current] : undefined;
      setLens(link && link.offsetWidth ? { x: link.offsetLeft, w: link.offsetWidth } : null);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(list);
    return () => observer.disconnect();
  }, [current]);

  return (
    <nav className="screens" aria-label="Screens">
      <div className="screens-list" ref={listRef}>
        <span
          className={`nav-lens${lens ? " on" : ""}`}
          aria-hidden="true"
          style={lens ? { transform: `translateX(${lens.x}px)`, width: lens.w } : undefined}
        />
        {SCREENS.map((s) => (
          <NavLink
            key={s.path}
            to={href(s.path)}
            className={({ isActive }) => (isActive ? "active" : undefined)}
            title={keysTitle(s.keys)}
          >
            <Icon name={SCREEN_ICONS[s.path]} stroke={1.8} className="nav-icon" />
            <span className="nav-label">{s.label}</span>
            {s.path === "/cases" && <PendingBadge />}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}

function FundSelect() {
  const { funds, fund, setFund, href } = useWorkspace();
  if (!fund) return null;
  return (
    <div className="fund-pick">
      <label className="field-inline">
        <span>Fund</span>
        <select className="glass-field" value={fund.code} onChange={(e) => setFund(e.target.value)}>
          {funds.map((f) => (
            <option key={f.code} value={f.code}>
              {f.code} · {f.name}
            </option>
          ))}
        </select>
      </label>
      <NavLink
        to={href(FUNDS_SCREEN.path)}
        className={({ isActive }) => (isActive ? "glass-chip funds-link active" : "glass-chip funds-link")}
        title={`Every fund, and this fund's settings (${keysTitle(FUNDS_SCREEN.keys)})`}
      >
        {FUNDS_SCREEN.label}
      </NavLink>
    </div>
  );
}

function DaySelect() {
  const { days, asOf, setDay } = useWorkspace();
  if (!days) return null;
  const options = days.days.map((d) => ({ value: d.as_of, label: `${dayLabel(d.as_of)} · ${dayStatusLabel(d.status)}` }));
  if (days.next_day && !options.some((o) => o.value === days.next_day)) {
    options.unshift({ value: days.next_day, label: `${dayLabel(days.next_day)} · ${dayStatusLabel(null)}` });
  }
  if (asOf && !options.some((o) => o.value === asOf)) {
    options.unshift({ value: asOf, label: `${dayLabel(asOf)} · ${dayStatusLabel(null)}` });
  }
  if (!options.length) return null;
  return (
    <label className="field-inline">
      <span>Business day</span>
      <select className="glass-field" value={asOf ?? ""} onChange={(e) => setDay(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Initials for the avatar: "Asha Rao" as AR. */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0] ?? "?";
  const last = parts.length > 1 ? (parts[parts.length - 1] ?? "") : "";
  return (last ? first.charAt(0) + last.charAt(0) : first.slice(0, 2)).toUpperCase();
}

/** One of the four avatar gradients, chosen by the name so a person keeps theirs. */
function avatarTone(name: string): number {
  let sum = 0;
  for (const ch of name) sum += ch.charCodeAt(0);
  return (sum % 4) + 1;
}

function UserMenu() {
  const user = useUser();
  const { signOut } = useAuth();
  const navigate = useNavigate();
  const { href } = useWorkspace();
  useCommand("Open administration", () => navigate(href(ADMIN_SCREEN.path)), {
    enabled: user.is_admin,
    keywords: "admin users funds settings ai calendar",
  });
  return (
    // Not modal: a modal menu locks page scroll with an injected <style>, which the CSP refuses.
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger className="glass-chip user-btn">
        <span className={`avatar avatar-${avatarTone(user.display_name)}`} aria-hidden="true">
          {initials(user.display_name)}
        </span>
        <span className="user-name">{user.display_name}</span>
        <span className="role-tag">{roleLabel(user.role)}</span>
        <Icon name="chevron" className="user-chev" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="menu" align="end" sideOffset={8}>
          <DropdownMenu.Label className="menu-label">
            Signed in as <strong>{user.username}</strong>, {roleLabel(user.role).toLowerCase()}
            {user.is_admin ? " and administrator" : ""}
          </DropdownMenu.Label>
          <DropdownMenu.Separator className="menu-sep" />
          {user.is_admin && (
            <DropdownMenu.Item className="menu-item" onSelect={() => navigate(href(ADMIN_SCREEN.path))}>
              <Icon name="admin" /> {ADMIN_SCREEN.label}
            </DropdownMenu.Item>
          )}
          <DropdownMenu.Item
            className="menu-item"
            onSelect={() => {
              void signOut().then(() => navigate("/signin", { replace: true }));
            }}
          >
            <Icon name="out" /> Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function TopBar({ onShowHelp, onOpenPalette }: { onShowHelp: () => void; onOpenPalette: () => void }) {
  const user = useUser();
  return (
    <header className="topbar">
      <div className="topbar-row topbar-main">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">ReconPilot</span>
        </div>
        <Screens />
        <div className="tools">
          <ThemeToggle />
          <button
            type="button"
            className="glass-btn"
            onClick={onShowHelp}
            aria-haspopup="dialog"
            aria-keyshortcuts="?"
            aria-label="Keyboard shortcuts"
            title="Keyboard shortcuts (?)"
          >
            <Icon name="key" />
          </button>
          <UserMenu />
        </div>
      </div>
      <div className="topbar-row topbar-sub">
        <div className="context">
          <FundSelect />
          <DaySelect />
        </div>
        <div className="finder">
          <button
            type="button"
            className="glass-chip palette-btn"
            onClick={onOpenPalette}
            aria-haspopup="dialog"
            aria-keyshortcuts="Control+K"
            title="Jump to a case, screen, fund or day, or run an action"
          >
            <Icon name="search" />
            <span className="palette-word">Search</span>
            <Kbd keys="mod+k" />
          </button>
          {user.demo && <RoleSwitcher user={user} />}
        </div>
      </div>
    </header>
  );
}
