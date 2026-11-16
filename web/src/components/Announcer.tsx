/**
 * One polite live region for the whole signed-in app, always in the page, so that results
 * which appear somewhere a screen-reader user is not looking (a decision recorded, a run
 * finished) are read out. A live region added to the page together with its text is often
 * not announced at all; one that is always there and only changes its text is.
 *
 * `useAnnounce()` returns `announce(message)`; outside the provider (a screen mounted on its
 * own in a unit test) it does nothing.
 */
import { type ReactNode, createContext, useCallback, useContext, useRef, useState } from "react";

type Announce = (message: string) => void;

const NBSP = String.fromCharCode(0xa0);

const AnnounceContext = createContext<Announce>(() => {});

export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");
  const flip = useRef(false);
  const announce = useCallback<Announce>((text) => {
    // The same words twice in a row (two approvals of different cases read alike) still need
    // announcing: a trailing non-breaking space changes the text without changing the words.
    flip.current = !flip.current;
    setMessage(flip.current ? text : `${text}${NBSP}`);
  }, []);
  return (
    <AnnounceContext.Provider value={announce}>
      {children}
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true" data-testid="announcer">
        {message}
      </p>
    </AnnounceContext.Provider>
  );
}

export function useAnnounce(): Announce {
  return useContext(AnnounceContext);
}
