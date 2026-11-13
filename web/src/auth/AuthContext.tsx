/**
 * Who is signed in.
 *
 * On start the app asks `GET /api/auth/me`; a 401 there simply means nobody is signed in.
 * A 401 on any later request means the session ended (idle or absolute timeout, signed out
 * elsewhere): the API client calls back here, the user is cleared along with every cached
 * query, and `RequireAuth` returns the person to sign-in.
 */
import { useQueryClient } from "@tanstack/react-query";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { ApiError, api, setUnauthorisedHandler } from "../api/client";
import { paths } from "../api/queries";
import type { LoginResponse, User } from "../api/types";

export type AuthState =
  | { status: "loading" }
  | { status: "signedOut"; expired: boolean }
  | { status: "signedIn"; user: User };

interface AuthValue {
  state: AuthState;
  user: User | null;
  signIn: (username: string, password: string) => Promise<User>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AuthState>({ status: "loading" });

  useEffect(() => {
    let live = true;
    api
      .get<User>(paths.me)
      .then((user) => {
        if (live) setState({ status: "signedIn", user });
      })
      .catch((error: unknown) => {
        if (!live) return;
        // Nobody signed in (401), or the API is unreachable: either way, offer sign-in.
        setState({ status: "signedOut", expired: false });
        if (!(error instanceof ApiError)) console.error(error);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    setUnauthorisedHandler(() => {
      queryClient.clear();
      setState((current) => (current.status === "signedIn" ? { status: "signedOut", expired: true } : current));
    });
    return () => setUnauthorisedHandler(null);
  }, [queryClient]);

  const signIn = useCallback(
    async (username: string, password: string) => {
      const { user } = await api.post<LoginResponse>(paths.login, { username, password });
      queryClient.clear();
      setState({ status: "signedIn", user });
      return user;
    },
    [queryClient],
  );

  const signOut = useCallback(async () => {
    try {
      await api.post<void>(paths.logout);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) throw error;
    } finally {
      queryClient.clear();
    }
    setState({ status: "signedOut", expired: false });
  }, [queryClient]);

  const value = useMemo<AuthValue>(
    () => ({ state, user: state.status === "signedIn" ? state.user : null, signIn, signOut }),
    [state, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth needs an AuthProvider");
  return value;
}

/** The signed-in user; only for components under `RequireAuth`. */
export function useUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("useUser called while signed out");
  return user;
}
