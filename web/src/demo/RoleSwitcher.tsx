/**
 * The demo's role switcher: become another of the fund's one-click users (an analyst, two
 * approvers, a viewer) to see what each may do. Each switch is a new session on the server,
 * which checks every role exactly as it would for real users.
 */
import "./demo.css";

import { useState } from "react";

import { ApiError } from "../api/client";
import type { User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { roleLabel } from "../vocabulary";

export function RoleSwitcher({ user }: { user: User }) {
  const { switchUser } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const members = user.demo?.users ?? [];
  if (!members.length) return null;

  async function change(username: string) {
    setBusy(true);
    setError(null);
    try {
      await switchUser(username);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not switch user. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="role-switch">
      <label className="field-inline">
        <span>Working as</span>
        <select className="glass-field" value={user.username} disabled={busy} onChange={(e) => void change(e.target.value)}>
          {members.map((m) => (
            <option key={m.username} value={m.username}>
              {m.display_name} · {roleLabel(m.role)}
            </option>
          ))}
        </select>
      </label>
      {error && (
        <span className="role-switch-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
