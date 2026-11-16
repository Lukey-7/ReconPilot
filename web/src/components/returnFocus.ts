/**
 * Focus back where it was when a dialog closes. Radix gives focus back to a dialog's
 * `Dialog.Trigger`, but these dialogs are opened by shortcuts, the palette or buttons that
 * are not triggers, so without this focus would fall to the top of the page on Esc.
 *
 * `useReturnFocus(open)` notes the focused element as the dialog opens and returns an
 * `onCloseAutoFocus` handler that puts focus back on it (or, if it has gone, on the screen's
 * title), unless an earlier handler already decided where focus goes.
 */
import { useLayoutEffect, useRef } from "react";

export function useReturnFocus(open: boolean): (event: Event) => void {
  const before = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (open) {
      const active = document.activeElement;
      before.current = active instanceof HTMLElement && active !== document.body ? active : null;
    }
  }, [open]);
  return (event: Event) => {
    if (event.defaultPrevented) return;
    event.preventDefault();
    const target = before.current;
    before.current = null;
    if (target?.isConnected) {
      target.focus({ preventScroll: true });
      return;
    }
    document.querySelector<HTMLElement>("main h1[tabindex]")?.focus({ preventScroll: true });
  };
}
