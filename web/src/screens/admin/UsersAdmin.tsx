/**
 * Users: everyone who can sign in, their role and whether they can now.
 *
 * The table is the whole job at a glance: name, role, administrator or not, active,
 * locked or deactivated, last sign-in and whether they are signed in now. "Manage" opens
 * one person's changes (role, administrator, reset password, unlock, deactivate) in a
 * dialog, so the table stays quiet. Every change is made by the server, ends the person's
 * sessions where it must (role, administrator, password, deactivation), and is written
 * to the audit log; the dialog says so in plain words. Your own account cannot be changed
 * here: another administrator does that.
 */
import * as Dialog from "@radix-ui/react-dialog";
import { type FormEvent, useId, useState } from "react";

import { ApiError } from "../../api/client";
import type { RoleName } from "../../api/types";
import { useUser } from "../../auth/AuthContext";
import { Icon } from "../../components/Icon";
import { ErrorLine, Loading } from "../../components/QueryState";
import { plural, timestamp } from "../../format";
import { ROLES, roleLabel } from "../../vocabulary";
import {
  type AdminUser,
  useAdminUsers,
  useChangeUser,
  useCreateUser,
  useResetPassword,
  useUnlockAccount,
} from "./api";

const ROLE_NAMES = Object.keys(ROLES) as RoleName[];
const MIN_PASSWORD = 12;

const ROLE_HINTS: Record<RoleName, string> = {
  analyst: "Works breaks: approves, rejects and reclassifies cases.",
  approver: "Decides material and escalated cases and signs off the NAV.",
  viewer: "Reads everything, changes nothing.",
};

function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return (
    <p className="form-error ad-form-error" role="alert">
      <Icon name="warn" />
      {message}
    </p>
  );
}

function Status({ user }: { user: AdminUser }) {
  if (!user.is_active) {
    return (
      <span className="ad-state">
        <Icon name="cross" /> Deactivated
      </span>
    );
  }
  if (user.locked) {
    return (
      <span className="ad-state locked">
        <Icon name="lock" /> Locked until {timestamp(user.locked_until)}
      </span>
    );
  }
  return (
    <span className="ad-state">
      <Icon name="check" /> Active
    </span>
  );
}

// --------------------------------------------------------------------------- add a user

function AddUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const create = useCreateUser();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<RoleName>("analyst");
  const [isAdmin, setIsAdmin] = useState(false);
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const ids = useId();

  function reset() {
    setUsername("");
    setDisplayName("");
    setRole("analyst");
    setIsAdmin(false);
    setPassword("");
    setAgain("");
    setProblem(null);
    create.reset();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== again) {
      setProblem("The two passwords differ.");
      return;
    }
    setProblem(null);
    create.mutate(
      { username: username.trim(), display_name: displayName.trim(), role, is_admin: isAdmin, password },
      {
        onSuccess: () => {
          reset();
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content className="dialog">
          <div className="dialog-head">
            <Dialog.Title>Add a user</Dialog.Title>
          </div>
          <Dialog.Description className="muted">
            They sign in with this username and password. The password needs at least {MIN_PASSWORD} characters and must
            not be a common one; give it to them in person and ask them to keep it to themselves.
          </Dialog.Description>
          <form className="ad-form two" onSubmit={submit}>
            <label className="ad-field" htmlFor={`${ids}-u`}>
              Username
              <input
                id={`${ids}-u`}
                className="input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="off"
                required
                maxLength={64}
              />
            </label>
            <label className="ad-field" htmlFor={`${ids}-n`}>
              Name
              <input
                id={`${ids}-n`}
                className="input"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="off"
                maxLength={128}
              />
            </label>
            <div className="ad-field ad-span">
              <label htmlFor={`${ids}-r`}>Role</label>
              <select
                id={`${ids}-r`}
                value={role}
                aria-describedby={`${ids}-rh`}
                onChange={(e) => setRole(e.target.value as RoleName)}
              >
                {ROLE_NAMES.map((r) => (
                  <option key={r} value={r}>
                    {roleLabel(r)}
                  </option>
                ))}
              </select>
              <span id={`${ids}-rh`} className="ad-hint">
                {ROLE_HINTS[role]}
              </span>
            </div>
            <label className="ad-field" htmlFor={`${ids}-p`}>
              Password
              <input
                id={`${ids}-p`}
                className="input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                required
                minLength={MIN_PASSWORD}
              />
            </label>
            <label className="ad-field" htmlFor={`${ids}-a`}>
              Password again
              <input
                id={`${ids}-a`}
                className="input"
                type="password"
                value={again}
                onChange={(e) => setAgain(e.target.value)}
                autoComplete="new-password"
                required
              />
            </label>
            <label className="ad-check ad-span">
              <input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
              <span>Administrator: may manage users and funds, switch AI and ask to unlock a signed-off day.</span>
            </label>
            <div className="ad-span">
              {problem ? (
                <p className="form-error ad-form-error" role="alert">
                  <Icon name="warn" />
                  {problem}
                </p>
              ) : (
                <FormError error={create.error} />
              )}
            </div>
            <div className="ad-dialog-actions ad-span">
              <Dialog.Close className="btn ghost" type="button" disabled={create.isPending}>
                Cancel
              </Dialog.Close>
              <button type="submit" className="btn primary" disabled={create.isPending}>
                {create.isPending ? "Adding…" : "Add user"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// --------------------------------------------------------------------------- manage one user

function ManageUserDialog({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const change = useChangeUser();
  const resetPassword = useResetPassword();
  const unlock = useUnlockAccount();
  const [role, setRole] = useState<RoleName>(user.role);
  const [password, setPassword] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const ids = useId();
  const busy = change.isPending || resetPassword.isPending || unlock.isPending;
  const error = change.error ?? resetPassword.error ?? unlock.error;
  const who = user.display_name || user.username;
  const sessions = user.live_sessions ? ` ${who} is signed out of ${plural(user.live_sessions, "session")} at once.` : "";

  function clearOutcome() {
    setDone(null);
    change.reset();
    resetPassword.reset();
    unlock.reset();
  }

  function saveRole() {
    clearOutcome();
    change.mutate(
      { username: user.username, change: { role } },
      { onSuccess: (u) => setDone(`${who} is now ${roleLabel(u.role).toLowerCase()}. Recorded in the audit log.`) },
    );
  }

  function toggleAdmin() {
    clearOutcome();
    change.mutate(
      { username: user.username, change: { is_admin: !user.is_admin } },
      {
        onSuccess: (u) =>
          setDone(`${who} ${u.is_admin ? "is now an administrator" : "is no longer an administrator"}. Recorded in the audit log.`),
      },
    );
  }

  function toggleActive() {
    clearOutcome();
    change.mutate(
      { username: user.username, change: { is_active: !user.is_active } },
      {
        onSuccess: (u) =>
          setDone(`${who} is ${u.is_active ? "active again and can sign in" : "deactivated and can no longer sign in"}.`),
      },
    );
  }

  function submitPassword(event: FormEvent) {
    event.preventDefault();
    clearOutcome();
    resetPassword.mutate(
      { username: user.username, password },
      {
        onSuccess: () => {
          setPassword("");
          setDone(`${who}'s password is reset. Give them the new one in person.`);
        },
      },
    );
  }

  function unlockAccount() {
    clearOutcome();
    unlock.mutate(user.username, { onSuccess: () => setDone(`${who} can sign in again.`) });
  }

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content className="dialog">
          <div className="dialog-head">
            <Dialog.Title>
              Manage {who} <span className="muted mono">{user.username}</span>
            </Dialog.Title>
          </div>
          <Dialog.Description className="muted">
            Each change takes effect at once and is recorded in the audit log under your name. A change of role,
            administrator rights or password signs {who} out everywhere.
          </Dialog.Description>
          <div className="ad-manage">
            {user.locked && (
              <div>
                <h3>Locked after failed sign-ins</h3>
                <p className="muted">Locked until {timestamp(user.locked_until)}. Unlock if you are sure it was them.</p>
                <div className="ad-row">
                  <button type="button" className="btn" onClick={unlockAccount} disabled={busy}>
                    <Icon name="lock" /> Unlock account
                  </button>
                </div>
              </div>
            )}
            <div>
              <h3>Role</h3>
              <div className="ad-row">
                <label className="ad-field" htmlFor={`${ids}-role`}>
                  Role
                  <select id={`${ids}-role`} value={role} onChange={(e) => setRole(e.target.value as RoleName)}>
                    {ROLE_NAMES.map((r) => (
                      <option key={r} value={r}>
                        {roleLabel(r)}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="button" className="btn" onClick={saveRole} disabled={busy || role === user.role}>
                  Change role
                </button>
              </div>
              <span className="faint">{ROLE_HINTS[role]}</span>
            </div>
            <div>
              <h3>Administrator</h3>
              <div className="ad-row">
                <span className="muted">{user.is_admin ? "Can manage users and funds." : "Cannot manage users or funds."}</span>
                <button type="button" className="btn" onClick={toggleAdmin} disabled={busy}>
                  {user.is_admin ? "Remove administrator" : "Make administrator"}
                </button>
              </div>
            </div>
            <div>
              <h3>Password</h3>
              <form className="ad-row" onSubmit={submitPassword}>
                <label className="ad-field" htmlFor={`${ids}-pw`}>
                  New password
                  <input
                    id={`${ids}-pw`}
                    className="input"
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    minLength={MIN_PASSWORD}
                    required
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </label>
                <button type="submit" className="btn" disabled={busy || !password}>
                  Reset password
                </button>
              </form>
            </div>
            <div>
              <h3>Access</h3>
              <div className="ad-row">
                <span className="muted">
                  {user.is_active ? `Active.${sessions ? " Deactivating signs them out." : ""}` : "Deactivated: cannot sign in."}
                </span>
                <button type="button" className="btn" onClick={toggleActive} disabled={busy}>
                  {user.is_active ? "Deactivate" : "Reactivate"}
                </button>
              </div>
            </div>
          </div>
          <div aria-live="polite">
            {done && (
              <p className="ad-done">
                <Icon name="check" />
                {done}
              </p>
            )}
          </div>
          <FormError error={error} />
          <div className="ad-dialog-actions">
            <Dialog.Close className="btn ghost">Done</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// --------------------------------------------------------------------------- the list

export function UsersAdmin() {
  const me = useUser();
  const users = useAdminUsers();
  const [adding, setAdding] = useState(false);
  const [managing, setManaging] = useState<string | null>(null);

  if (users.isPending) return <Loading label="Loading users" />;
  if (users.isError) return <ErrorLine error={users.error} retry={() => void users.refetch()} />;
  const list = users.data;
  const current = managing ? list.find((u) => u.username === managing) : undefined;
  const locked = list.filter((u) => u.locked).length;

  return (
    <section className="ad-block" aria-labelledby="ad-h-users">
      <div className="ad-block-head">
        <h2 id="ad-h-users">Users</h2>
        <span className="muted">
          {plural(list.filter((u) => u.is_active).length, "active user")}
          {locked ? `, ${plural(locked, "locked account")}` : ""}
        </span>
        <button type="button" className="btn" onClick={() => setAdding(true)}>
          Add a user
        </button>
      </div>
      <div className="table-wrap">
        <table className="data-table ad-users">
          <caption className="sr-only">Every user, their role, whether they are an administrator and can sign in</caption>
          <thead>
            <tr>
              <th scope="col">User</th>
              <th scope="col">Role</th>
              <th scope="col">Administrator</th>
              <th scope="col">Status</th>
              <th scope="col">Last sign-in</th>
              <th scope="col">Signed in now</th>
              <th scope="col">
                <span className="sr-only">Manage</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {list.map((u) => (
              <tr key={u.username} className={u.is_active ? undefined : "ad-inactive"}>
                <th scope="row">
                  {u.display_name}
                  <span className="ad-handle mono">{u.username}</span>
                </th>
                <td>{roleLabel(u.role)}</td>
                <td>{u.is_admin ? "Yes" : "No"}</td>
                <td>
                  <Status user={u} />
                </td>
                <td>{u.last_login_at ? timestamp(u.last_login_at) : "Never"}</td>
                <td>{u.live_sessions ? "Yes" : "No"}</td>
                <td className="ad-action">
                  {u.username === me.username ? (
                    <span className="tag">You</span>
                  ) : (
                    <button
                      type="button"
                      className="btn"
                      aria-label={`Manage ${u.display_name} (${u.username})`}
                      onClick={() => setManaging(u.username)}
                    >
                      Manage
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="faint">Your own account is changed by another administrator, so nobody can lock everyone out.</p>
      <AddUserDialog open={adding} onOpenChange={setAdding} />
      {current && <ManageUserDialog key={current.username} user={current} onClose={() => setManaging(null)} />}
    </section>
  );
}
