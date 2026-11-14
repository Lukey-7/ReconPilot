/**
 * Funds: every fund the desk services, and the settings of the fund being worked.
 *
 * One job: know which fund you are in and the rules it runs by. The list shows each
 * fund's latest business day and its status; "Work this fund" switches to it and stores
 * the choice for the user. The settings are read-only here (an administrator changes
 * them): materiality, escalation and SLA days, the AI second opinion, the release checks
 * as the engine applies them, and the business calendar. Every value is the server's.
 */
import "./funds.css";

import { useFund } from "../../api/queries";
import type { FundDetail, FundSummary } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { count, dayLabel } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { ASSET_CLASS_LABELS, CHECK_SETTING_LABELS, dayStatusLabel } from "../../vocabulary";

function number(value: number, decimals = 2): string {
  return value.toLocaleString("en-GB", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function percent(fraction: number): string {
  return `${number(fraction * 100)}%`;
}

function days(n: number): string {
  return `${count(n)} business ${n === 1 ? "day" : "days"}`;
}

function FundList({ funds, current }: { funds: FundSummary[]; current: string }) {
  const { setFund } = useWorkspace();
  return (
    <section className="fd-block" aria-labelledby="fd-h-list">
      <h2 id="fd-h-list">Every fund</h2>
      <div className="table-wrap">
        <table className="data-table fd-list">
          <caption className="sr-only">Every fund, its latest business day and that day&rsquo;s status</caption>
          <thead>
            <tr>
              <th scope="col">Fund</th>
              <th scope="col">Base currency</th>
              <th scope="col">First business day</th>
              <th scope="col">Latest day</th>
              <th scope="col">Status</th>
              <th scope="col">
                <span className="sr-only">Work</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {funds.map((f) => {
              const working = f.code === current;
              return (
                <tr key={f.code} aria-current={working ? "true" : undefined} className={working ? "fd-current" : undefined}>
                  <th scope="row">
                    <span className="mono">{f.code}</span> <span className="fd-name">{f.name}</span>
                  </th>
                  <td>{f.base_currency}</td>
                  <td>{dayLabel(f.start_date)}</td>
                  <td>{f.latest_day ? dayLabel(f.latest_day) : "None loaded"}</td>
                  <td>{dayStatusLabel(f.latest_status)}</td>
                  <td className="fd-action">
                    {working ? (
                      <span className="tag">
                        <Icon name="check" /> Working
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn"
                        aria-label={`Work this fund: ${f.code}`}
                        onClick={() => setFund(f.code)}
                      >
                        Work this fund
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** One setting: its name, its value, and where the value comes from when that matters. */
function Setting({ name, value, note, own }: { name: string; value: string; note?: string; own?: boolean }) {
  return (
    <div className="fd-setting">
      <dt>{name}</dt>
      <dd>
        <span className="fd-value">{value}</span>
        {own !== undefined && <span className="tag fd-source">{own ? "This fund" : "Engine default"}</span>}
        {note && <span className="fd-note">{note}</span>}
      </dd>
    </div>
  );
}

function Settings({ fund }: { fund: FundDetail }) {
  const s = fund.settings;
  const checks = fund.checks_in_force;
  const own = (key: string) => Object.prototype.hasOwnProperty.call(s.check_settings, key);
  const limits = Object.entries(checks.price_move_limits)
    .map(([assetClass, limit]) => `${ASSET_CLASS_LABELS[assetClass] ?? assetClass} ${percent(limit)}`)
    .join(", ");
  return (
    <section className="fd-block" aria-labelledby="fd-h-settings">
      <div className="fd-block-head">
        <h2 id="fd-h-settings">
          Settings for <span className="mono">{fund.code}</span>
        </h2>
        <span className="tag">
          <Icon name="lock" /> Read-only
        </span>
      </div>
      <p className="muted">
        The rules {fund.name}&rsquo;s days are run and released by. An administrator changes them; a change applies
        from the next run.
      </p>

      <div className="fd-groups">
        <div className="fd-group">
          <h3>Cases</h3>
          <dl>
            <Setting
              name="Materiality"
              value={`${number(s.materiality_bp)} bp of NAV`}
              note="A case is material when its NAV impact is at least this; material cases block release until approved or reclassified."
            />
            <Setting
              name="Escalation"
              value={`Open longer than ${days(s.escalate_after_days)}`}
              note="Material cases are escalated at once; escalated cases need an approver's decision."
            />
            <Setting name="SLA, material cases" value={days(s.sla_days_material)} />
            <Setting name="SLA, other cases" value={days(s.sla_days_other)} />
            <Setting
              name="AI second opinion"
              value={s.ai_enabled ? "On" : "Off"}
              note={
                s.ai_enabled
                  ? "The AI explains each new case beside the rules' suggestion; people decide."
                  : "Cases carry the rules' suggestion only."
              }
            />
          </dl>
        </div>

        <div className="fd-group">
          <h3>Release checks</h3>
          <dl>
            <Setting
              name={CHECK_SETTING_LABELS.max_price_age_days}
              value={`At most ${count(checks.max_price_age_days)} ${checks.max_price_age_days === 1 ? "day" : "days"} old`}
              own={own("max_price_age_days")}
            />
            <Setting
              name={CHECK_SETTING_LABELS.movement_threshold}
              value={`Warn beyond ${percent(checks.movement_threshold)} a day`}
              own={own("movement_threshold")}
            />
            <Setting
              name={CHECK_SETTING_LABELS.cash_tolerance}
              value={`${number(checks.cash_tolerance)} ${fund.base_currency}`}
              own={own("cash_tolerance")}
            />
            <Setting name={CHECK_SETTING_LABELS.price_move_limits} value={limits} own={own("price_move_limits")} />
          </dl>
        </div>

        <div className="fd-group">
          <h3>Business calendar</h3>
          <dl>
            <Setting name="First business day" value={dayLabel(fund.start_date)} />
            <Setting
              name="Non-business days"
              value={
                fund.non_business_dates.length
                  ? fund.non_business_dates.map((d) => dayLabel(d)).join("; ")
                  : "Weekends only"
              }
              note="Days are worked in order: each business day is signed off before the next one's files are loaded."
            />
          </dl>
        </div>
      </div>
    </section>
  );
}

function SettingsArea({ code }: { code: string }) {
  const detail = useFund(code);
  if (detail.isPending) return <Loading label="Loading the fund's settings" />;
  if (detail.isError) return <ErrorLine error={detail.error} retry={() => void detail.refetch()} />;
  return <Settings fund={detail.data} />;
}

export function FundsScreen() {
  const { funds, fund, fundsLoading } = useWorkspace();

  let body;
  if (!fund) body = fundsLoading ? <Loading label="Loading funds" /> : <Empty>No fund is set up yet.</Empty>;
  else
    body = (
      <div className="fd-grid">
        <FundList funds={funds} current={fund.code} />
        <SettingsArea code={fund.code} />
      </div>
    );

  return (
    <section className="screen fd-screen">
      <ScreenHeader title="Funds">
        {fund && (
          <p className="muted">
            {funds.length === 1 ? "1 fund" : `${count(funds.length)} funds`}; working {fund.code}, {fund.name}
          </p>
        )}
      </ScreenHeader>
      {body}
    </section>
  );
}
