/**
 * The top bar: screens, the fund and business day being worked, the signed-in user and
 * their role, the theme and the shortcuts. One row, nothing decorative.
 */
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { NavLink, useNavigate } from "react-router";

import { useRelease } from "../api/queries";
import { useAuth, useUser } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Kbd } from "../components/Kbd";
import { count, dayLabel } from "../format";
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

/** Every fund and the chosen fund's settings: reached from beside the fund selector, not the screen list. */
export const FUNDS_SCREEN = { path: "/funds", label: "Funds", keys: "g f" } as const;

function PendingBadge() {
  const { fund, asOf } = useWorkspace();
  const release = useRelease(fund?.code ?? null, asOf);
  const pending = release.data?.reasons.find((r) => r.code === "PENDING_DECISIONS")?.case_ids.length ?? 0;
  if (!pending) return null;
  return (
    <span className="badge" title={`${pending} pending a decision`}>
      {count(pending)}
      <span className="sr-only"> pending a decision</span>
    </span>
  );
}

function FundSelect() {
  const { funds, fund, setFund, href } = useWorkspace();
  if (!fund) return null;
  return (
    <div className="fund-pick">
      <label className="field-inline">
        <span>Fund</span>
        <select value={fund.code} onChange={(e) => setFund(e.target.value)}>
          {funds.map((f) => (
            <option key={f.code} value={f.code}>
              {f.code} · {f.name}
            </option>
          ))}
        </select>
      </label>
      <NavLink
        to={href(FUNDS_SCREEN.path)}
        className={({ isActive }) => (isActive ? "btn ghost funds-link active" : "btn ghost funds-link")}
        title="Every fund, and this fund's settings"
      >
        {FUNDS_SCREEN.label}
        <Kbd keys={FUNDS_SCREEN.keys} />
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
      <select value={asOf ?? ""} onChange={(e) => setDay(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function UserMenu() {
  const user = useUser();
  const { signOut } = useAuth();
  const navigate = useNavigate();
  return (
    // Not modal: a modal menu locks page scroll with an injected <style>, which the CSP refuses.
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger className="btn ghost user-btn">
        <Icon name="user" />
        <span className="user-name">{user.display_name}</span>
        <span className="role-tag">{roleLabel(user.role)}</span>
        <Icon name="chevron" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="menu" align="end" sideOffset={6}>
          <DropdownMenu.Label className="menu-label">
            Signed in as <strong>{user.username}</strong>, {roleLabel(user.role).toLowerCase()}
            {user.is_admin ? " and administrator" : ""}
          </DropdownMenu.Label>
          <DropdownMenu.Separator className="menu-sep" />
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

export function TopBar({ onShowHelp }: { onShowHelp: () => void }) {
  const { href } = useWorkspace();
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-name">ReconPilot</span>
      </div>
      <nav className="screens" aria-label="Screens">
        {SCREENS.map((s) => (
          <NavLink key={s.path} to={href(s.path)} className={({ isActive }) => (isActive ? "active" : undefined)}>
            {s.label}
            {s.path === "/cases" && <PendingBadge />}
            <Kbd keys={s.keys} />
          </NavLink>
        ))}
      </nav>
      <div className="context">
        <FundSelect />
        <DaySelect />
      </div>
      <div className="tools">
        <ThemeToggle />
        <button type="button" className="btn ghost" onClick={onShowHelp} aria-haspopup="dialog">
          <Icon name="key" /> Shortcuts
          <Kbd keys="?" />
        </button>
        <UserMenu />
      </div>
    </header>
  );
}
