/**
 * The lead figure counts up when a day loads or changes (Paper's count-up, 700 to 1100 ms,
 * ease-out cubic): from zero for a new fund or day, from where it was for a new value on the
 * same day (a rerun). A missing value and every value under reduced motion show at once,
 * and the figure always settles on exactly `target`.
 */
import { useEffect, useRef, useState } from "react";

import { usePrefersReducedMotion } from "../../motion";

export const COUNT_UP_MS = 900;

function easeOutCubic(t: number): number {
  return 1 - (1 - t) ** 3;
}

export function useCountUp(target: number | null, scope: string, duration = COUNT_UP_MS): number | null {
  const reduced = usePrefersReducedMotion();
  const [shown, setShown] = useState<number | null>(() =>
    target == null || reduced || typeof window.requestAnimationFrame !== "function" ? target : 0,
  );
  const at = useRef<number | null>(null);
  const seen = useRef<string | null>(null);

  useEffect(() => {
    const sameScope = seen.current === scope;
    seen.current = scope;
    if (target == null || reduced || typeof window.requestAnimationFrame !== "function") {
      at.current = target;
      setShown(target);
      return;
    }
    const from = sameScope && at.current != null ? at.current : 0;
    if (from === target) {
      at.current = target;
      setShown(target);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const step = () => {
      const now = performance.now();
      const t = Math.min(1, Math.max(0, (now - start) / duration));
      const value = t >= 1 ? target : from + (target - from) * easeOutCubic(t);
      at.current = value;
      setShown(value);
      if (t < 1) frame = window.requestAnimationFrame(step);
    };
    frame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(frame);
  }, [target, scope, reduced, duration]);

  return reduced ? target : shown;
}
