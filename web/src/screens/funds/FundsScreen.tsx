/**
 * Funds: every fund the desk services, and the settings of the fund being worked.
 *
 * One job: know which fund you are in and the rules it runs by. The lead card counts the
 * funds; the list shows each fund's latest business day and its status; "Work this fund"
 * switches to it and stores the choice for the user. The settings are read-only here (an
 * administrator changes them), as records: materiality, escalation and SLA days, the AI
 * second opinion, the release checks as the engine applies them, and the business
 * calendar, its non-business days as chips. Every value is the server's.
 */
import "./funds.css";

import type { ReactNode } from "react";
import { Link } from "react-router";

import { useFund } from "../../api/queries";
import type { FundDetail, FundSummary } from "../../api/types";
import { useUser } from "../../auth/AuthContext";
import { Icon } from "../../components/Icon";
import { type StatusKind, StatusPill } from "../../components/Labels";
import { Lead, SectionHead } from "../../components/Paper";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { ScreenHeader } from "../../components/ScreenHeader";
import { count, dayLabel, plural } from "../../format";
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

/** A day's status as a pill: signed off green, waiting on review amber, failed red. */
const DAY_KINDS: Record<string, StatusKind> = {
  uploaded: "late",
  validated: "wait",
  running: "info",
  ready: "wait",
  signed_off: "done",
  failed: "late",
};

function FundLead({ funds }: { funds: FundSummary[] }) {
  const signedOff = funds.filter((f) => f.latest_status === "signed_off").length;
  return (
    <Lead
      className="fd-lead"
      aria-label="Funds"
      label="Funds the desk services"
      figure={count(funds.length)}
      caption={`${count(signedOff)} of ${plural(funds.length, "fund")} signed off on their latest day`}
    />
  );
}

function FundList({ funds, current }: { funds: FundSummary[]; current: string }) {
  const { setFund } = useWorkspace();
  return (
    <section className="fd-section" aria-labelledby="fd-h-list">
      <SectionHead label="Funds" title="Every fund" count={count(funds.length)} id="fd-h-list" />
      <ul className="list fd-list" aria-label="Every fund, its latest business day and that day’s status">
        {funds.map((f) => {
          const working = f.code === current;
          return (
            <li
              key={f.code}
              aria-current={working ? "true" : undefined}
              className={working ? "row fd-fund fd-current" : "row fd-fund"}
            >
              <div className="row-main">
                <p className="row-title">
                  <span className="mono">{f.code}</span> <span className="fd-name">{f.name}</span>
                </p>
                <p className="row-sub">
                  {f.base_currency} · First business day {dayLabel(f.start_date)} · Latest day:{" "}
                  {f.latest_day ? dayLabel(f.latest_day) : "None loaded"}
                </p>
                <p className="fd-pills">
                  <StatusPill kind={(f.latest_status && DAY_KINDS[f.latest_status]) || "neutral"}>
                    {dayStatusLabel(f.latest_status)}
                  </StatusPill>
                </p>
              </div>
              <div className="fd-action">
                {working ? (
                  <span className="tag">
                    <Icon name="check" /> Working
                  </span>
                ) : (
                  <button
                    type="button"
                    className="btn quiet"
                    aria-label={`Work this fund: ${f.code}`}
                    onClick={() => setFund(f.code)}
                  >
                    Work this fund
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** One setting as a record: its name left, its value right, and a note beneath when it helps. */
function Setting({ name, value, note, own }: { name: string; value: ReactNode; note?: string; own?: boolean }) {
  return (
    <div className="record fd-setting">
      <dt>{name}</dt>
      <dd className="fd-value">
        {own !== undefined && <span className="tag fd-source">{own ? "This fund" : "Engine default"}</span>}
        <span>{value}</span>
      </dd>
      {note && <dd className="fd-note">{note}</dd>}
    </div>
  );
}

function Settings({ fund }: { fund: FundDetail }) {
  const user = useUser();
  const { href } = useWorkspace();
  const s = fund.settings;
  const checks = fund.checks_in_force;
  const own = (key: string) => Object.prototype.hasOwnProperty.call(s.check_settings, key);
  const limits = Object.entries(checks.price_move_limits)
    .map(([assetClass, limit]) => `${ASSET_CLASS_LABELS[assetClass] ?? assetClass} ${percent(limit)}`)
    .join(", ");
  return (
    <section className="card fd-block" aria-labelledby="fd-h-settings">
      <div className="fd-block-head">
        <SectionHead
          label="Rules"
          title={
            <>
              Settings for <span className="mono">{fund.code}</span>
            </>
          }
          id="fd-h-settings"
        />
        <span className="tag">
          <Icon name="lock" /> Read-only
        </span>
        {user.is_admin && (
          <Link className="btn quiet fd-admin-link" to={href("/admin/funds")}>
            Change settings
          </Link>
        )}
      </div>
      <p className="muted">
        The rules {fund.name}&rsquo;s days are run and released by. An administrator changes them; a change applies
        from the next run.
      </p>

      <div className="fd-groups">
        <div className="fd-group">
          <h3 className="mono-label">Cases</h3>
          <dl className="records">
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
          <h3 className="mono-label">Release checks</h3>
          <dl className="records">
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
          <h3 className="mono-label">Business calendar</h3>
          <dl className="records">
            <Setting name="First business day" value={dayLabel(fund.start_date)} />
            <Setting
              name="Non-business days"
              value={
                fund.non_business_dates.length ? (
                  <ul className="fd-dates" aria-label="Non-business days">
                    {fund.non_business_dates.map((d) => (
                      <li key={d}>{dayLabel(d)}</li>
                    ))}
                  </ul>
                ) : (
                  "Weekends only"
                )
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
      <>
        <FundLead funds={funds} />
        <div className="fd-grid">
          <FundList funds={funds} current={fund.code} />
          <SettingsArea code={fund.code} />
        </div>
      </>
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
