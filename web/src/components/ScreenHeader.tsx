/**
 * A screen's heading. Focus moves to it when the screen opens (by link or shortcut), so a
 * screen reader announces where the person now is and Tab continues from the top.
 */
import { type ReactNode, useEffect, useRef } from "react";

export function ScreenHeader({ title, children }: { title: string; children?: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.focus({ preventScroll: true });
  }, [title]);
  return (
    <div className="screen-head">
      <h1 ref={ref} tabIndex={-1}>
        {title}
      </h1>
      {children}
    </div>
  );
}
