/**
 * Sign-in with a built-in account. The server decides everything (lockout after five
 * failures, 423 while locked); this screen shows its answer in plain words and returns the
 * person to the page they were going to.
 */
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { ApiError } from "../api/client";
import { Icon } from "../components/Icon";
import { ThemeToggle } from "../theme/ThemeProvider";
import { useAuth } from "./AuthContext";
import type { SignInState } from "./RequireAuth";

const HOME = "/overview";

/** Only paths inside the app, and never back to sign-in itself. */
export function safeDestination(from: string | undefined): string {
  if (!from || !from.startsWith("/") || from.startsWith("//") || from.startsWith("/signin")) return HOME;
  return from;
}

export function SignInScreen() {
  const { state, signIn } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const nav = (location.state ?? {}) as SignInState;
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const errorRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  if (state.status === "signedIn" && !busy) return <Navigate to={safeDestination(nav.from)} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError("Enter your username and password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
      navigate(safeDestination(nav.from), { replace: true });
    } catch (err) {
      setPassword("");
      setError(err instanceof ApiError ? err.message : "Could not sign in. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin-page">
      <div className="signin-theme">
        <ThemeToggle />
      </div>
      <main className="signin-card" aria-labelledby="signin-title">
        <p className="signin-brand">ReconPilot</p>
        <h1 id="signin-title">Sign in</h1>
        <p className="muted signin-lede">Fund reconciliation, break triage and NAV sign-off.</p>
        {nav.expired && !error && (
          <p className="notice" role="status">
            <Icon name="clock" /> Your session ended. Sign in again to carry on where you were.
          </p>
        )}
        {error && (
          <p className="form-error" role="alert" tabIndex={-1} ref={errorRef}>
            <Icon name="warn" /> {error}
          </p>
        )}
        <form onSubmit={submit} noValidate>
          <label className="field">
            <span>Username</span>
            <input
              className="input"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={busy}
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              className="input"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy}
            />
          </label>
          <button type="submit" className="btn primary signin-submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </main>
    </div>
  );
}
