/**
 * Loading, error and empty states for a query, so a screen shows one calm line instead of
 * a broken layout. Errors use the server's own words (ApiError's message).
 */
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { Icon } from "./Icon";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="state-line" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}…
    </p>
  );
}

export function ErrorLine({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return (
    <div className="state-line error" role="alert">
      <Icon name="warn" />
      <span>{message}</span>
      {retry && (
        <button type="button" className="btn ghost" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty-state">{children}</p>;
}
