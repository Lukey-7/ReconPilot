/**
 * What the server found when it re-checked the whole chain, in plain words. An intact chain
 * says how many entries were checked, when and by whom; a broken one names the first entry
 * that does not fit, shows that entry, and says what to do.
 */
import { useAuditEntry } from "../../api/queries";
import type { ChainCheck } from "../../api/types";
import { Icon } from "../../components/Icon";
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
      <div className="al-verdict tone-met" role="status">
        <Icon name="check" />
        <p>
          <strong>Chain intact.</strong> All {plural(check.entries, "entry", "entries")} re-checked on the server: every
          hash recomputes and each names the one before it. Checked {when}; the check itself is entry #{check.seq}.
        </p>
      </div>
    );
  }
  return (
    <div className="al-verdict tone-broken" role="alert">
      <Icon name="warn" />
      <div>
        <p>
          <strong>Chain broken at entry #{check.broken_at ?? "?"}.</strong> That entry, or one before it, was changed or
          removed after it was written, so the log from there on cannot be relied on. Report it to your control team
          before relying on the log. Checked {when}.
        </p>
        {check.broken_at != null && <BrokenEntry seq={check.broken_at} />}
      </div>
    </div>
  );
}
