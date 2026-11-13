/** Shows its children to a signed-in user; otherwise sends the person to sign-in, and back again after. */
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { Loading } from "../components/QueryState";
import { useAuth } from "./AuthContext";

export interface SignInState {
  from?: string;
  expired?: boolean;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "loading") {
    return (
      <div className="boot">
        <Loading label="Opening ReconPilot" />
      </div>
    );
  }
  if (state.status === "signedOut") {
    const to: SignInState = { from: `${location.pathname}${location.search}`, expired: state.expired };
    return <Navigate to="/signin" replace state={to} />;
  }
  return <>{children}</>;
}
