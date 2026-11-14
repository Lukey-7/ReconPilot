/**
 * One audit entry in full, on demand: the server's check of the entry itself (its hash
 * recomputes from its fields, and it names the hash of the entry before it), then exactly
 * what was recorded: when, by whom, the payload and both hashes.
 */
import { useAuditEntry } from "../../api/queries";
import type { AuditLogEntry } from "../../api/types";
import { Icon } from "../../components/Icon";
import { ErrorLine } from "../../components/QueryState";
import { roleLabel } from "../../vocabulary";

function Check({ ok, yes, no }: { ok: boolean; yes: string; no: string }) {
  return (
    <li className={ok ? "al-check tone-met" : "al-check tone-broken"}>
      <Icon name={ok ? "check" : "warn"} />
      <span>{ok ? yes : no}</span>
    </li>
  );
}

function Integrity({ seq }: { seq: number }) {
  const query = useAuditEntry(seq);
  if (query.isPending) {
    return (
      <p className="al-checking faint" role="status">
        Checking this entry on the server…
      </p>
    );
  }
  if (query.isError) return <ErrorLine error={query.error} retry={() => void query.refetch()} />;
  const entry = query.data;
  return (
    <ul className="al-checks" aria-label={`Server check of entry #${seq}`}>
      <Check
        ok={entry.hash_ok}
        yes="Its hash recomputes from what it records."
        no="Its hash does not match what it records: the entry was changed after it was written."
      />
      <Check
        ok={entry.linked}
        yes={seq === 1 ? "It starts the chain." : `It names the hash of entry #${seq - 1}.`}
        no={
          seq === 1
            ? "It does not start the chain as the first entry must."
            : `It does not name the hash of entry #${seq - 1}: an entry before it was changed or removed.`
        }
      />
    </ul>
  );
}

export function EntryDetail({ entry }: { entry: AuditLogEntry }) {
  return (
    <div className="al-detail">
      <Integrity seq={entry.seq} />
      <dl className="al-fields">
        <div>
          <dt>Recorded</dt>
          <dd className="fig">{entry.ts}</dd>
        </div>
        <div>
          <dt>By</dt>
          <dd>
            {entry.actor}
            {entry.role && <span className="faint"> ({roleLabel(entry.role)})</span>}
          </dd>
        </div>
        <div>
          <dt>Action</dt>
          <dd className="fig">{entry.action}</dd>
        </div>
        <div>
          <dt>Fund</dt>
          <dd>{entry.fund ?? <span className="faint">None (a system entry)</span>}</dd>
        </div>
        <div className="al-wide">
          <dt>Previous hash</dt>
          <dd className="al-hash">{entry.prev_hash}</dd>
        </div>
        <div className="al-wide">
          <dt>Hash</dt>
          <dd className="al-hash">{entry.hash}</dd>
        </div>
      </dl>
      <p className="al-payload-h">Recorded payload</p>
      <pre className="al-payload">
        {JSON.stringify(entry.payload, null, 2)}
      </pre>
    </div>
  );
}
