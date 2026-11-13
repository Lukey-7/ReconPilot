/** A screen that is not built yet. Says so plainly rather than showing made-up figures. */
import type { ReactNode } from "react";

export function Placeholder({ children }: { children: ReactNode }) {
  return <div className="placeholder">{children}</div>;
}
