/**
 * Administration (spec section 10, screen 7): two jobs, one tab each.
 *
 * - **Users**: who can sign in and as what; add, change role, deactivate, reset a
 *   password, unlock a locked account.
 * - **Funds**: the fund being worked: its settings, its business calendar and the AI
 *   switch (with the warning that evidence leaves the firm); add a fund.
 *
 * Reached from the user menu and the palette, and only offered to an administrator. The
 * server refuses everyone else whatever the browser shows.
 */
import "./admin.css";

import { NavLink } from "react-router";

import { useUser } from "../../auth/AuthContext";
import { Empty } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { useWorkspace } from "../../shell/workspace";
import { FundsAdmin } from "./FundsAdmin";
import { UsersAdmin } from "./UsersAdmin";

export const ADMIN_TABS = [
  { path: "/admin/users", label: "Users" },
  { path: "/admin/funds", label: "Funds" },
] as const;

export function AdminScreen({ tab }: { tab: "users" | "funds" }) {
  const user = useUser();
  const { href } = useWorkspace();
  const title = tab === "users" ? "Administration: users" : "Administration: funds";

  if (!user.is_admin) {
    return (
      <section className="screen ad-screen">
        <ScreenHeader title="Administration" />
        <Empty>Only an administrator can manage users and funds. Ask one if something needs changing.</Empty>
      </section>
    );
  }

  return (
    <section className="screen ad-screen">
      <ScreenHeader title={title} />
      <nav className="seg ad-tabs" aria-label="Administration">
        {ADMIN_TABS.map((t) => (
          <NavLink key={t.path} to={href(t.path)} className={({ isActive }) => (isActive ? "active" : undefined)}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      {tab === "users" ? <UsersAdmin /> : <FundsAdmin />}
    </section>
  );
}
