/**
 * The audit log's lead card: the chain's integrity. Until someone asks, it says the chain has
 * not been verified yet; "Verify chain" (the screen's one primary) has the server re-check
 * every hash. Then the lead says what the server found, in plain words: an intact chain says
 * how many entries were checked, when and by whom; a broken one names the first entry that
 * does not fit, in red with its word, shows that entry, and says what to do.
 */
import type { ReactNode } from "react";

import { useAuditEntry } from "../../api/queries";
import type { ChainCheck } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Lead } from "../../components/Paper";
import { ErrorLine } from "../../components/QueryState";
import { plural, timestamp } from "../../format";
import { EntryDetail } from "./EntryDetail";

function BrokenEntry({ seq }: { seq: number }) {
  const query = useAuditEntry(seq);
  if (!query.data) return null;
  return (
    <details className="al-broken-entry">
      <summary>Show entry #{seq}</summary>
      <EntryDetail entry={query.data} />
    </details>
  );
}

export function ChainVerdict({ check, me }: { check: ChainCheck; me: string }) {
  const who = check.verified_by === me ? "you" : check.verified_by;
  const when = `${timestamp(check.verified_at)}, by ${who}`;
  if (check.chain_ok) {
    return (
      <div className="al-verdict" role="status">
        <p>
          <strong>Chain intact.</strong> All {plural(check.entries, "entry", "entries")} re-checked on the server: every
          hash recomputes and each names the one before it. Checked {when}; the check itself is entry #{check.seq}.
        </p>
      </div>
    );
  }
  return (
    <div className="al-verdict" role="alert">
      <p>
        <strong>Chain broken at entry #{check.broken_at ?? "?"}.</strong> That entry, or one before it, was changed or
        removed after it was written, so the log from there on cannot be relied on. Report it to your control team
        before relying on the log. Checked {when}.
      </p>
      {check.broken_at != null && <BrokenEntry seq={check.broken_at} />}
    </div>
  );
}

export function ChainLead({
  check,
  error,
  me,
  actions,
}: {
  check: ChainCheck | undefined;
  error: Error | null;
  me: string;
  actions: ReactNode;
}) {
  let word: ReactNode;
  let tone: string;
  if (!check) {
    tone = "unchecked";
    word = "Not verified yet";
  } else if (check.chain_ok) {
    tone = "intact";
    word = (
      <>
        <Icon name="check" className="al-lead-icon" />
        Intact
      </>
    );
  } else {
    tone = "broken";
    word = (
      <>
        <Icon name="warn" className="al-lead-icon" />
        Broken at <span className="al-lead-seq">#{check.broken_at ?? "?"}</span>
      </>
    );
  }
  const counted = check ? check.entries : null;
  return (
    <Lead
      className={`al-lead al-lead-${tone}`}
      aria-label="Chain integrity"
      label="Chain integrity"
      figure={
        <>
          <span className="al-lead-word">{word}</span>
          {counted != null && (
            <span className="al-lead-count">
              {plural(counted, "entry", "entries")}
              {" checked"}
            </span>
          )}
        </>
      }
      caption={
        <>
          {check ? (
            <ChainVerdict check={check} me={me} />
          ) : (
            <p>Verify chain re-checks every entry&rsquo;s hash on the server, and records that it did.</p>
          )}
          {error && <ErrorLine error={error} />}
        </>
      }
      foot={actions}
    />
  );
}
