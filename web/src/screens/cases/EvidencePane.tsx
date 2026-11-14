/**
 * Pane 3: the evidence. The book against the custodian for the case's security, the breaks
 * the matcher found (book, custodian and the difference), the NAV impact if the custodian
 * is right, and the records behind the case from the day's files on demand.
 *
 * The pane collapses to a rail (more room for the case and long AI text) or widens (more
 * room for the figures); the choice is the viewer's own and is remembered in this browser.
 */
import type { ReactNode } from "react";

import type { CaseDetail } from "../../api/types";
import { Icon } from "../../components/Icon";
import { MISSING, bp, count, dayLabel, money } from "../../format";
import { breakKindLabel } from "../../vocabulary";

export type EvidenceMode = "normal" | "wide" | "collapsed";

const PRICE_DECIMALS = 4;

function price(value: number | null | undefined): string {
  return money(value, { decimals: PRICE_DECIMALS });
}

function quantity(value: number | null | undefined, signed = false): string {
  if (value == null) return MISSING;
  return Number.isInteger(value) ? (signed && value > 0 ? `+${count(value)}` : count(value)) : money(value, { signed, decimals: 4 });
}

/** The difference cell: custodian less book, or "agrees". */
function Diff({ book, custodian, format }: { book?: number | null; custodian?: number | null; format: (v: number) => string }) {
  if (book == null || custodian == null) return <td className="num">{MISSING}</td>;
  const diff = custodian - book;
  const shown = format(diff);
  if (Number(shown.replace(/[^0-9.]/g, "")) === 0) {
    return (
      <td className="num wb-agree">
        <Icon name="check" />
        agrees
      </td>
    );
  }
  return <td className="num wb-diff">{shown}</td>;
}

function Section({ id, title, meta, children }: { id: string; title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="wb-section" aria-labelledby={id}>
      <div className="wb-section-h">
        <h3 id={id}>{title}</h3>
        {meta && <span className="wb-section-meta">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

function Position({ detail }: { detail: CaseDetail }) {
  const book = detail.book_position;
  const cust = detail.custodian_holding;
  if (!book && !cust) {
    return (
      <p className="muted">
        No position on either side: {detail.security_id ? "neither holds this security." : "the custodian sent no security identifier with this cash."}
      </p>
    );
  }
  const currency = book?.currency ?? cust?.currency ?? "";
  return (
    <>
      <table className="wb-ev-table">
        <caption className="sr-only">Position, book against custodian</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="sr-only">Figure</span>
            </th>
            <th scope="col" className="num">
              Book
            </th>
            <th scope="col" className="num">
              Custodian
            </th>
            <th scope="col" className="num">
              Difference
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Quantity</th>
            <td className="num">{quantity(book?.quantity)}</td>
            <td className="num">{quantity(cust?.quantity)}</td>
            <Diff book={book?.quantity} custodian={cust?.quantity} format={(v) => quantity(v, true)} />
          </tr>
          <tr>
            <th scope="row">Price{currency ? ` (${currency})` : ""}</th>
            <td className="num">{price(book?.price)}</td>
            <td className="num">{price(cust?.price)}</td>
            <Diff book={book?.price} custodian={cust?.price} format={(v) => money(v, { signed: true, decimals: PRICE_DECIMALS })} />
          </tr>
        </tbody>
      </table>
      {book?.price_date && <p className="wb-note">Book price dated {dayLabel(book.price_date)}.</p>}
    </>
  );
}

function breakFormat(kind: string): (v: number | null, signed?: boolean) => string {
  if (kind === "PRICE") return (v, signed) => money(v, { signed, decimals: PRICE_DECIMALS });
  if (kind === "QUANTITY") return (v, signed) => quantity(v, signed);
  return (v, signed) => money(v, { signed });
}

function Breaks({ detail, currency }: { detail: CaseDetail; currency: string }) {
  if (!detail.breaks.length) return <p className="muted">No breaks recorded for this case on this day.</p>;
  return (
    <table className="wb-ev-table">
      <caption className="sr-only">Breaks in this case</caption>
      <thead>
        <tr>
          <th scope="col">Break</th>
          <th scope="col" className="num">
            Book
          </th>
          <th scope="col" className="num">
            Custodian
          </th>
          <th scope="col" className="num">
            Difference
          </th>
        </tr>
      </thead>
      <tbody>
        {detail.breaks.map((b) => {
          const f = breakFormat(b.kind);
          return (
            <tr key={b.break_id}>
              <th scope="row">
                <span className="wb-ev-kind">
                  {breakKindLabel(b.kind)}
                  {b.kind.startsWith("CASH") && currency ? `, ${currency}` : ""}
                </span>
                <span className="wb-sub">{b.break_id}</span>
                {b.reference && <span className="wb-sub">Ref {b.reference}</span>}
                {b.note && <span className="wb-sub">{b.note}</span>}
              </th>
              <td className="num">{b.book_value == null ? <span className="faint">none</span> : f(b.book_value)}</td>
              <td className="num">{b.custodian_value == null ? <span className="faint">none</span> : f(b.custodian_value)}</td>
              <td className="num wb-diff">{f(b.difference, true)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Records({ detail }: { detail: CaseDetail }) {
  const n =
    detail.book_trades.length + detail.book_cash.length + detail.custodian_cash.length + detail.carried_items.length;
  if (!n) return null;
  return (
    <details className="wb-records">
      <summary>
        Records behind this case <span className="faint">({count(n)} from the day&rsquo;s files)</span>
      </summary>
      {detail.book_trades.length > 0 && (
        <table className="wb-ev-table">
          <caption>Book trades</caption>
          <thead>
            <tr>
              <th scope="col">Trade</th>
              <th scope="col" className="num">
                Quantity
              </th>
              <th scope="col" className="num">
                Price
              </th>
            </tr>
          </thead>
          <tbody>
            {detail.book_trades.map((t) => (
              <tr key={t.trade_id}>
                <th scope="row">
                  {t.trade_id}
                  <span className="wb-sub">
                    {t.side === "BUY" ? "Buy" : t.side === "SELL" ? "Sell" : t.side}, traded {dayLabel(t.trade_date)}, settles{" "}
                    {dayLabel(t.settle_date)}
                  </span>
                </th>
                <td className="num">{quantity(t.quantity)}</td>
                <td className="num">
                  {price(t.price)}
                  <span className="wb-sub">{t.currency}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {detail.book_cash.length > 0 && (
        <table className="wb-ev-table">
          <caption>Book cash</caption>
          <tbody>
            {detail.book_cash.map((e, i) => (
              <tr key={`${e.reference}-${i}`}>
                <th scope="row">
                  {e.reference || e.description}
                  <span className="wb-sub">
                    {e.description}, value {dayLabel(e.value_date)}
                  </span>
                </th>
                <td className="num">{money(e.amount, { signed: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {detail.custodian_cash.length > 0 && (
        <table className="wb-ev-table">
          <caption>Custodian cash</caption>
          <tbody>
            {detail.custodian_cash.map((e) => (
              <tr key={e.entry_id}>
                <th scope="row">
                  {e.reference || e.entry_id}
                  <span className="wb-sub">
                    {e.description}, value {dayLabel(e.value_date)}
                  </span>
                </th>
                <td className="num">{money(e.amount, { signed: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {detail.carried_items.length > 0 && (
        <table className="wb-ev-table">
          <caption>Carried from the previous day</caption>
          <tbody>
            {detail.carried_items.map((e, i) => (
              <tr key={`${e.side}-${e.reference ?? e.entry_id ?? i}`}>
                <th scope="row">
                  {e.reference || e.entry_id || MISSING}
                  <span className="wb-sub">
                    {e.side === "book" ? "Book" : "Custodian"}
                    {e.origin_date ? `, since ${dayLabel(e.origin_date)}` : e.value_date ? `, value ${dayLabel(e.value_date)}` : ""}
                  </span>
                </th>
                <td className="num">{money(e.amount, { signed: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}

export function EvidencePane({
  detail,
  currency,
  mode,
  setMode,
}: {
  detail: CaseDetail | undefined;
  currency: string;
  mode: EvidenceMode;
  setMode: (mode: EvidenceMode) => void;
}) {
  if (mode === "collapsed") {
    return (
      <section className="wb-pane wb-ev-pane wb-ev-collapsed" aria-label="Evidence (collapsed)">
        <button type="button" className="btn ghost wb-ev-rail" onClick={() => setMode("normal")} aria-label="Show the evidence">
          <Icon name="eye" />
          <span className="wb-rail-label" aria-hidden="true">
            Evidence
          </span>
        </button>
      </section>
    );
  }
  return (
    <section className="wb-pane wb-ev-pane" aria-labelledby="wb-h-ev">
      <div className="wb-pane-head">
        <h2 id="wb-h-ev">Evidence</h2>
        <span className="wb-pane-meta">book against custodian</span>
        <span className="wb-pane-tools">
          <button
            type="button"
            className="btn ghost"
            aria-pressed={mode === "wide"}
            onClick={() => setMode(mode === "wide" ? "normal" : "wide")}
          >
            {mode === "wide" ? "Narrow" : "Widen"}
          </button>
          <button type="button" className="btn ghost" onClick={() => setMode("collapsed")}>
            Hide
          </button>
        </span>
      </div>
      <div className="wb-pane-body wb-ev-body">
        {!detail ? (
          <p className="wb-empty">Open a case to see its evidence.</p>
        ) : (
          <>
            <Section
              id="wb-h-pos"
              title="Position"
              meta={detail.security ? `${detail.security.name} (${detail.security.security_id})` : detail.security_id || "no security id"}
            >
              <Position detail={detail} />
            </Section>
            <Section id="wb-h-breaks" title="Breaks" meta={`${count(detail.breaks.length)} on this case`}>
              <Breaks detail={detail} currency={currency} />
            </Section>
            <Section id="wb-h-impact" title="NAV impact" meta="if the custodian is right">
              <dl className="wb-impact">
                <div>
                  <dt>Net</dt>
                  <dd className="fig">{money(detail.nav_impact, { signed: true })}</dd>
                </div>
                <div>
                  <dt>Of NAV</dt>
                  <dd className="fig">{bp(detail.nav_impact_bp)}</dd>
                </div>
                <div>
                  <dt>Gross</dt>
                  <dd className="fig">{money(detail.gross_exposure)}</dd>
                </div>
              </dl>
              {detail.fx_rate != null && detail.security && detail.security.currency !== currency && (
                <p className="wb-note">
                  {detail.security.currency} to {currency} at {money(detail.fx_rate, { decimals: 6 })}.
                </p>
              )}
            </Section>
            <Records detail={detail} />
          </>
        )}
      </div>
    </section>
  );
}
