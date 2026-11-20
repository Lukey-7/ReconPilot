/**
 * The head of management information: the lead card with the gross open NAV impact (gains
 * and losses added without netting, so offsetting breaks cannot hide each other) and how it
 * moved across the run days of the period, then four tiles with the headline figures: net
 * impact, open breaks, the average business days to resolve and the SLA breaches. Every
 * figure is the server's; the period's mini bars only repeat the trend's gross figures,
 * which the trend's table gives in full, so they are hidden from assistive tech.
 */
import type { Mi } from "../../api/types";
import { TweenedMoney } from "../../components/Figures";
import { StatusPill } from "../../components/Labels";
import { Lead, Tile, Tiles } from "../../components/Paper";
import { count, dayLabel, dayShort, money, plural } from "../../format";

/** A figure longer than this many characters shrinks on its tile rather than wrap. */
const LONG = 11;

function PeriodBars({ mi }: { mi: Mi }) {
  const max = Math.max(1, ...mi.trend.map((d) => d.open_gross_impact));
  return (
    <span className="mi-lead-bars" aria-hidden="true">
      {mi.trend.map((d) => (
        <span
          key={d.as_of}
          className={d.as_of === mi.as_of ? "mi-lead-bar current" : "mi-lead-bar"}
          style={{
            height: `${Math.max(8, (d.open_gross_impact / max) * 100)}%`,
          }}
        />
      ))}
    </span>
  );
}

export function MiHeadline({ mi }: { mi: Mi }) {
  const currency = mi.fund.base_currency;
  const total = mi.by_cause_age.total;
  const today = mi.trend.find((d) => d.as_of === mi.as_of);
  const first = mi.trend[0];
  const last = mi.trend[mi.trend.length - 1];
  const resolve = mi.time_to_resolve.all;
  const slaOpen = mi.sla_breaches.filter((c) => !c.cleared_on).length;
  const net = money(total.net, { signed: true });

  let period: string;
  if (!first || !last) period = dayLabel(mi.as_of);
  else if (first === last) period = `${dayLabel(first.as_of)}, the only run day so far`;
  else period = `Across ${plural(mi.trend.length, "run day")}, ${dayShort(first.as_of)} to ${dayShort(last.as_of)}`;

  return (
    <>
      <Lead
        className="mi-lead"
        aria-label="Gross open NAV impact"
        label="Gross open NAV impact"
        figure={
          <>
            <TweenedMoney value={total.gross} /> <span className="mi-lead-unit">{currency}</span>
          </>
        }
        caption={`${total.count ? plural(total.count, "open case") : "No case open"} at the end of ${dayLabel(
          mi.as_of,
        )}, gains and losses added without netting.`}
        foot={
          <>
            {mi.trend.length > 1 && <PeriodBars mi={mi} />}
            <span className="mi-lead-period">{period}</span>
          </>
        }
      />
      <section className="mi-tiles" aria-label="Headline figures">
        <Tiles count={4}>
          <Tile
            label="Net impact"
            long={net.length > LONG}
            figure={
              <>
                {net} <span className="mi-tile-unit">{currency}</span>
              </>
            }
            note="Gains and losses offset"
          />
          <Tile
            label="Open breaks"
            figure={count(total.count)}
            note={
              today
                ? `${count(today.material_open)} material, ${count(today.aged_over_5)} over 5 business days`
                : undefined
            }
          />
          <Tile
            label="Average business days to resolve"
            figure={resolve.avg_days == null ? "None yet" : money(resolve.avg_days)}
            note={resolve.cleared ? `over ${plural(resolve.cleared, "cleared case")}` : "Nothing cleared yet"}
          />
          <Tile
            label="SLA breaches"
            figure={count(slaOpen)}
            note={`still open, ${count(mi.sla_breaches.length - slaOpen)} since cleared`}
            foot={
              slaOpen ? (
                <StatusPill kind="late">Past SLA</StatusPill>
              ) : (
                <StatusPill kind="done">None open past SLA</StatusPill>
              )
            }
          />
        </Tiles>
      </section>
    </>
  );
}
