/**
 * Motion is subtle (150 to 200 ms) and switched off entirely for people who ask for less:
 * CSS transitions and animations through styles/tokens.css, and anything animated from
 * script (figure tweens) through the hooks here.
 *
 * Motion only ever explains a change: a figure easing from its old value to its new one,
 * the release status announcing that it moved, rows arriving in a list, a pane swapping.
 * Nothing moves on its own, and nothing moves under `prefers-reduced-motion: reduce`.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

/** How long a figure takes to ease to its new value. */
export const TWEEN_MS = 200;

function subscribe(onChange: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(QUERY).matches;
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false);
}

/** Ease out: quick to start, gentle to settle, so the new figure is readable at once. */
function easeOut(t: number): number {
  return 1 - (1 - t) ** 3;
}

/**
 * A figure that eases from its previous value to `target` over `duration` ms. The first
 * value, a missing value (null) and every value under reduced motion show at once; an
 * interrupted tween carries on from where it had got to. The figure always settles on
 * exactly `target`.
 */
export function useTween<T extends number | null | undefined>(target: T, duration = TWEEN_MS): T | number {
  const reduced = usePrefersReducedMotion();
  const [shown, setShown] = useState<T | number>(target);
  const at = useRef<T | number>(target);

  useEffect(() => {
    const from = at.current;
    const animate =
      !reduced &&
      typeof from === "number" &&
      typeof target === "number" &&
      from !== target &&
      Number.isFinite(from) &&
      typeof window.requestAnimationFrame === "function";
    if (!animate) {
      at.current = target;
      setShown(target);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, Math.max(0, (now - start) / duration));
      const value = t >= 1 ? target : from + (target - from) * easeOut(t);
      at.current = value;
      setShown(value);
      if (t < 1) frame = window.requestAnimationFrame(step);
    };
    frame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(frame);
  }, [target, reduced, duration]);

  return reduced ? target : shown;
}

/**
 * How many times `value` has changed while `scope` stayed the same: 0 at first, then 1, 2
 * and so on. A new scope (another fund or day) starts again at 0 without counting, so only
 * a change in place counts. Values seen while not `ready` (still loading) are ignored.
 * Used as a React key, it replays an entry animation each time the value changes.
 */
export function useChangeCount(value: unknown, scope: string, ready = true): number {
  const [seen, setSeen] = useState<{ value: unknown; scope: string; count: number } | null>(null);
  let current = seen;
  if (ready) {
    if (seen == null || seen.scope !== scope) current = { value, scope, count: 0 };
    else if (!Object.is(seen.value, value)) current = { value, scope, count: seen.count + 1 };
    if (current !== seen) setSeen(current); // adjusting state while rendering, as React documents
  }
  return current != null && current.scope === scope ? current.count : 0;
}
