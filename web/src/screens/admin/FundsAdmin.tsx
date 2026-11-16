/**
 * Funds: the settings of the fund being worked, its business calendar and its AI switch.
 *
 * The fund is the one chosen in the top bar, like every other screen. Three panels:
 *
 * - **Settings**: the fund's name, materiality, escalation and SLA days and the release
 *   checks. Saving sends only what changed; the server checks every value and records each
 *   change, from and to, in the audit log. Settings apply from the fund's next run.
 * - **AI second opinion**: off until an administrator switches it on. Switching on names a
 *   provider the server has configured and asks the administrator to confirm, in a dialog,
 *   that the day's evidence will leave the firm (or, for the private endpoint, go to the
 *   host shown). Audited with the provider and model.
 * - **Business calendar**: non-business dates, changeable only after the latest loaded day.
 *
 * "Add a fund" creates one (AI off) and switches to it. Every value shown is the server's.
 */
import * as Dialog from "@radix-ui/react-dialog";
import { type FormEvent, useId, useState } from "react";

import { ApiError } from "../../api/client";
import { Icon } from "../../components/Icon";
import { Empty, ErrorLine, Loading } from "../../components/QueryState";
import { dayLabel } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { ASSET_CLASS_LABELS, CHECK_SETTING_LABELS } from "../../vocabulary";
import {
  type AdminFund,
  type AiProvider,
  type AiProviders,
  useAdminFund,
  useAiProviders,
  useChangeFund,
  useCreateFund,
  useSwitchAi,
} from "./api";

function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.message : "Something went wrong.";
  return (
    <p className="form-error ad-form-error" role="alert">
      <Icon name="warn" />
      {message}
    </p>
  );
}

function Saved({ text }: { text: string | null }) {
  return (
    <span className="ad-saved" aria-live="polite">
      {text && (
        <>
          <Icon name="check" />
          {text}
        </>
      )}
    </span>
  );
}

/** A number as a form shows it: no trailing zeros, no exponent. */
function shown(value: number): string {
  return String(Number(value.toFixed(10)));
}

function percentShown(fraction: number): string {
  return shown(fraction * 100);
}

/** The typed text as a number, or NaN when it is not one. */
function parsed(text: string): number {
  return text.trim() === "" ? Number.NaN : Number(text);
}

function same(a: number, b: number): boolean {
  return Math.abs(a - b) < 1e-9;
}

// --------------------------------------------------------------------------- settings

interface SettingsDraft {
  name: string;
  materiality_bp: string;
  escalate_after_days: string;
  sla_days_material: string;
  sla_days_other: string;
  max_price_age_days: string;
  movement_threshold_pct: string;
  cash_tolerance: string;
  limits_pct: Record<string, string>;
}

function draftOf(fund: AdminFund): SettingsDraft {
  const s = fund.settings;
  const c = fund.checks_in_force;
  return {
    name: fund.name,
    materiality_bp: shown(s.materiality_bp),
    escalate_after_days: shown(s.escalate_after_days),
    sla_days_material: shown(s.sla_days_material),
    sla_days_other: shown(s.sla_days_other),
    max_price_age_days: shown(c.max_price_age_days),
    movement_threshold_pct: percentShown(c.movement_threshold),
    cash_tolerance: shown(c.cash_tolerance),
    limits_pct: Object.fromEntries(Object.entries(c.price_move_limits).map(([k, v]) => [k, percentShown(v)])),
  };
}

/** What the draft changes, as the PATCH body wants it; a message when a value is not a number. */
function settingsChange(
  fund: AdminFund,
  draft: SettingsDraft,
): { change: { name?: string; settings?: Record<string, unknown> }; problem: string | null } {
  const change: { name?: string; settings?: Record<string, unknown> } = {};
  const settings: Record<string, unknown> = {};
  const fields: [keyof SettingsDraft & keyof AdminFund["settings"], string][] = [
    ["materiality_bp", "Materiality"],
    ["escalate_after_days", "Escalation"],
    ["sla_days_material", "SLA for material cases"],
    ["sla_days_other", "SLA for other cases"],
  ];
  for (const [key, label] of fields) {
    const value = parsed(draft[key] as string);
    if (Number.isNaN(value)) return { change, problem: `${label} must be a number.` };
    if (!same(value, fund.settings[key] as number)) settings[key] = value;
  }

  const inForce = fund.checks_in_force;
  const checks: Record<string, unknown> = {};
  const age = parsed(draft.max_price_age_days);
  const movement = parsed(draft.movement_threshold_pct) / 100;
  const cash = parsed(draft.cash_tolerance);
  if ([age, movement, cash].some(Number.isNaN)) return { change, problem: "Every release check needs a number." };
  if (!same(age, inForce.max_price_age_days)) checks.max_price_age_days = age;
  if (!same(movement, inForce.movement_threshold)) checks.movement_threshold = Number(movement.toFixed(10));
  if (!same(cash, inForce.cash_tolerance)) checks.cash_tolerance = cash;
  const limits: Record<string, number> = {};
  let limitsChanged = false;
  for (const [asset, text] of Object.entries(draft.limits_pct)) {
    const value = parsed(text) / 100;
    if (Number.isNaN(value)) return { change, problem: "Every price-move limit needs a number." };
    limits[asset] = Number(value.toFixed(10));
    if (!same(value, inForce.price_move_limits[asset] ?? Number.NaN)) limitsChanged = true;
  }
  if (limitsChanged) checks.price_move_limits = limits;
  if (Object.keys(checks).length) settings.check_settings = { ...fund.settings.check_settings, ...checks };

  if (Object.keys(settings).length) change.settings = settings;
  if (draft.name.trim() !== fund.name) change.name = draft.name.trim();
  return { change, problem: null };
}

function NumberField({
  label,
  unit,
  value,
  onChange,
  step = "any",
  hint,
}: {
  label: string;
  unit: string;
  value: string;
  onChange: (value: string) => void;
  step?: string;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="ad-field">
      <label htmlFor={id}>{label}</label>
      <span className="ad-unit">
        <input
          id={id}
          className="input mono"
          type="number"
          inputMode="decimal"
          min="0"
          step={step}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={hint ? `${id}-hint` : undefined}
        />
        <span>{unit}</span>
      </span>
      {hint && (
        <span id={`${id}-hint`} className="ad-hint">
          {hint}
        </span>
      )}
    </div>
  );
}

function SettingsPanel({ fund }: { fund: AdminFund }) {
  const save = useChangeFund(fund.code);
  const [draft, setDraft] = useState(() => draftOf(fund));
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const nameId = useId();
  const set = (key: keyof SettingsDraft) => (value: string) => {
    setSaved(null);
    setDraft((d) => ({ ...d, [key]: value }));
  };
  const { change } = settingsChange(fund, draft);
  const dirty = Object.keys(change).length > 0;

  function submit(event: FormEvent) {
    event.preventDefault();
    const result = settingsChange(fund, draft);
    setProblem(result.problem);
    if (result.problem || !Object.keys(result.change).length) return;
    save.mutate(result.change, {
      onSuccess: (updated) => {
        setDraft(draftOf(updated));
        setSaved("Saved. Applies from the next run; recorded in the audit log.");
      },
    });
  }

  return (
    <section className="ad-block" aria-labelledby="ad-h-settings">
      <h2 id="ad-h-settings">
        Settings for <span className="mono">{fund.code}</span>
      </h2>
      <form className="ad-form two" onSubmit={submit}>
        <div className="ad-field ad-span">
          <label htmlFor={nameId}>Fund name</label>
          <input
            id={nameId}
            className="input"
            value={draft.name}
            maxLength={200}
            required
            onChange={(e) => set("name")(e.target.value)}
          />
        </div>
        <h3 className="ad-span">Cases</h3>
        <NumberField
          label="Materiality"
          unit="bp of NAV"
          value={draft.materiality_bp}
          onChange={set("materiality_bp")}
          hint="Material cases block release until approved or reclassified."
        />
        <NumberField
          label="Escalate after"
          unit="business days open"
          step="1"
          value={draft.escalate_after_days}
          onChange={set("escalate_after_days")}
        />
        <NumberField
          label="SLA, material cases"
          unit="business days"
          step="1"
          value={draft.sla_days_material}
          onChange={set("sla_days_material")}
        />
        <NumberField
          label="SLA, other cases"
          unit="business days"
          step="1"
          value={draft.sla_days_other}
          onChange={set("sla_days_other")}
        />
        <h3 className="ad-span">Release checks</h3>
        <NumberField
          label={CHECK_SETTING_LABELS.max_price_age_days}
          unit="days old at most"
          step="1"
          value={draft.max_price_age_days}
          onChange={set("max_price_age_days")}
        />
        <NumberField
          label={CHECK_SETTING_LABELS.movement_threshold}
          unit="% a day"
          value={draft.movement_threshold_pct}
          onChange={set("movement_threshold_pct")}
        />
        <NumberField
          label={CHECK_SETTING_LABELS.cash_tolerance}
          unit={fund.base_currency}
          value={draft.cash_tolerance}
          onChange={set("cash_tolerance")}
        />
        {Object.keys(draft.limits_pct).map((asset) => (
          <NumberField
            key={asset}
            label={`Price-move limit, ${ASSET_CLASS_LABELS[asset] ?? asset}`}
            unit="% a day"
            value={draft.limits_pct[asset] ?? ""}
            onChange={(value) => {
              setSaved(null);
              setDraft((d) => ({ ...d, limits_pct: { ...d.limits_pct, [asset]: value } }));
            }}
          />
        ))}
        <div className="ad-span">
          {problem ? (
            <p className="form-error ad-form-error" role="alert">
              <Icon name="warn" />
              {problem}
            </p>
          ) : (
            <FormError error={save.error} />
          )}
        </div>
        <div className="ad-actions ad-span">
          <Saved text={saved} />
          <button
            type="button"
            className="btn ghost"
            disabled={!dirty || save.isPending}
            onClick={() => {
              setDraft(draftOf(fund));
              setProblem(null);
              save.reset();
            }}
          >
            Undo changes
          </button>
          <button type="submit" className="btn primary" disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving…" : "Save settings"}
          </button>
        </div>
      </form>
    </section>
  );
}

// --------------------------------------------------------------------------- AI switch

function providerName(providers: AiProviders, name: string | null): string {
  if (!name) return "none";
  return providers.providers.find((p) => p.provider === name)?.label ?? name;
}

/** Where the evidence goes, in one phrase. */
function destination(p: AiProvider): string {
  return p.private ? `the private endpoint at ${p.endpoint ?? "the configured host"}` : `${p.label}, outside the firm`;
}

function SwitchOnDialog({
  fund,
  provider,
  chosen,
  open,
  onOpenChange,
}: {
  fund: AdminFund;
  provider: AiProvider;
  /** The fund's own choice, or null for the server's default. */
  chosen: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const switchAi = useSwitchAi(fund.code);
  const [understood, setUnderstood] = useState(false);
  const checkId = useId();
  const warning = provider.private ? "Evidence goes to your private endpoint" : "Evidence leaves the building";

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setUnderstood(false);
          switchAi.reset();
        }
        onOpenChange(next);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content className="dialog">
          <div className="dialog-head">
            <Dialog.Title>Switch AI on for {fund.code}?</Dialog.Title>
          </div>
          <div className="notice ad-warn" role="note">
            <Icon name="warn" />
            <div>
              <strong>{warning}.</strong> From the next run, the evidence behind each new case (its positions, trades,
              prices and cash lines, with the rules&rsquo; suggestion) is sent to {destination(provider)}
              {provider.model ? `, model ${provider.model}` : ""}.
            </div>
          </div>
          <Dialog.Description className="muted">
            The AI gives a second opinion beside the rules and drafts a custodian query; it never decides. Its answers are
            checked for invented figures and recorded in the audit log. Switching on is recorded under your name with the
            provider and model.
          </Dialog.Description>
          <label className="ad-check ad-ack" htmlFor={checkId}>
            <input id={checkId} type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} />
            <span>I understand that {fund.code}&rsquo;s evidence will be sent to {destination(provider)}.</span>
          </label>
          <FormError error={switchAi.error} />
          <div className="ad-dialog-actions">
            <Dialog.Close className="btn ghost" disabled={switchAi.isPending}>
              Cancel
            </Dialog.Close>
            <button
              type="button"
              className="btn primary"
              disabled={!understood || switchAi.isPending}
              onClick={() =>
                switchAi.mutate(
                  { enabled: true, provider: chosen, acknowledged: true },
                  { onSuccess: () => onOpenChange(false) },
                )
              }
            >
              {switchAi.isPending ? "Switching on…" : "Switch AI on"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const SERVER_DEFAULT = "";

function AiPanel({ fund }: { fund: AdminFund }) {
  const providers = useAiProviders();
  const switchAi = useSwitchAi(fund.code);
  const [choice, setChoice] = useState<string>(fund.ai.provider ?? SERVER_DEFAULT);
  const [confirming, setConfirming] = useState(false);
  const selectId = useId();

  let body;
  if (providers.isPending) body = <Loading label="Asking the server which AI providers it has" />;
  else if (providers.isError) body = <ErrorLine error={providers.error} retry={() => void providers.refetch()} />;
  else {
    const list = providers.data;
    const effective = choice === SERVER_DEFAULT ? list.default : choice;
    const target = list.providers.find((p) => p.provider === effective) ?? null;
    const unchanged = fund.ai.enabled && (fund.ai.provider ?? SERVER_DEFAULT) === choice;
    const defaultLabel = list.default ? `Server default (${providerName(list, list.default)})` : "Server default (none set)";
    body = (
      <>
        <p className="ad-ai-state">
          {fund.ai.enabled ? (
            <>
              <span className="tag on">
                <Icon name="check" /> On
              </span>
              {providerName(list, fund.ai.effective_provider)}
              {fund.ai.model && <span className="muted mono">{fund.ai.model}</span>}
            </>
          ) : (
            <>
              <span className="tag">
                <Icon name="ring" /> Off
              </span>
              <span className="muted">Cases carry the rules&rsquo; suggestion only.</span>
            </>
          )}
        </p>
        <div className="ad-row">
          <div className="ad-field">
            <label htmlFor={selectId}>Provider</label>
            <select id={selectId} value={choice} onChange={(e) => setChoice(e.target.value)}>
              <option value={SERVER_DEFAULT} disabled={!list.default}>
                {defaultLabel}
              </option>
              {list.providers.map((p) => (
                <option key={p.provider} value={p.provider} disabled={!p.configured}>
                  {p.label}
                  {p.configured ? "" : " (not configured)"}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn primary"
            disabled={!target?.configured || unchanged}
            onClick={() => setConfirming(true)}
          >
            {fund.ai.enabled ? "Use this provider…" : "Switch AI on…"}
          </button>
          {fund.ai.enabled && (
            <button
              type="button"
              className="btn"
              disabled={switchAi.isPending}
              onClick={() => switchAi.mutate({ enabled: false, provider: null, acknowledged: false })}
            >
              {switchAi.isPending ? "Switching off…" : "Switch AI off"}
            </button>
          )}
        </div>
        <FormError error={switchAi.error} />
        <details>
          <summary className="muted">What the server has</summary>
          <ul className="ad-providers">
            {list.providers.map((p) => (
              <li key={p.provider}>
                <span>{p.label}</span>
                <span className="muted">
                  {p.configured
                    ? `Configured; model ${p.model ?? "default"}${p.private && p.endpoint ? `, at ${p.endpoint}` : ""}.`
                    : p.problem}
                </span>
              </li>
            ))}
          </ul>
        </details>
        {target?.configured && (
          <SwitchOnDialog
            fund={fund}
            provider={target}
            chosen={choice === SERVER_DEFAULT ? null : choice}
            open={confirming}
            onOpenChange={setConfirming}
          />
        )}
      </>
    );
  }

  return (
    <section className="ad-block" aria-labelledby="ad-h-ai">
      <h2 id="ad-h-ai">AI second opinion</h2>
      <p className="muted">
        Off until an administrator switches it on. Keys stay on the server; this page never sees them.
      </p>
      {body}
    </section>
  );
}

// --------------------------------------------------------------------------- calendar

function CalendarPanel({ fund }: { fund: AdminFund }) {
  const save = useChangeFund(fund.code);
  const [adding, setAdding] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const dateId = useId();
  const horizon = fund.latest_day;
  const editable = (d: string) => horizon === null || d > horizon;

  function update(dates: string[], message: string) {
    setSaved(null);
    save.mutate({ non_business_dates: dates }, { onSuccess: () => setSaved(message) });
  }

  function add(event: FormEvent) {
    event.preventDefault();
    if (!adding || fund.non_business_dates.includes(adding)) return;
    update([...fund.non_business_dates, adding].sort(), `${dayLabel(adding)} is now a non-business day.`);
    setAdding("");
  }

  return (
    <section className="ad-block" aria-labelledby="ad-h-cal">
      <h2 id="ad-h-cal">Business calendar</h2>
      <p className="muted">
        Weekdays from {dayLabel(fund.start_date)} are business days, except these.{" "}
        {horizon
          ? `Dates up to the latest loaded day, ${dayLabel(horizon)}, cannot change: those days were worked on this calendar.`
          : "No day has been loaded yet, so any later date can change."}
      </p>
      {fund.non_business_dates.length ? (
        <ul className="ad-dates" aria-label="Non-business days">
          {fund.non_business_dates.map((d) => (
            <li key={d}>
              <span>{dayLabel(d)}</span>
              {editable(d) ? (
                <button
                  type="button"
                  className="btn ghost"
                  aria-label={`Remove ${dayLabel(d)}`}
                  disabled={save.isPending}
                  onClick={() =>
                    update(
                      fund.non_business_dates.filter((x) => x !== d),
                      `${dayLabel(d)} is a business day again.`,
                    )
                  }
                >
                  Remove
                </button>
              ) : (
                <span className="faint">
                  <Icon name="lock" /> Worked
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <Empty>Weekends only, so far.</Empty>
      )}
      <form className="ad-row" onSubmit={add}>
        <div className="ad-field">
          <label htmlFor={dateId}>Add a non-business day</label>
          <input
            id={dateId}
            className="input"
            type="date"
            value={adding}
            min={horizon ?? undefined}
            onChange={(e) => setAdding(e.target.value)}
          />
        </div>
        <button type="submit" className="btn" disabled={!adding || save.isPending}>
          Add
        </button>
      </form>
      <div className="ad-actions">
        <Saved text={saved} />
      </div>
      <FormError error={save.error} />
    </section>
  );
}

// --------------------------------------------------------------------------- add a fund

function AddFundDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const create = useCreateFund();
  const { setFund } = useWorkspace();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [start, setStart] = useState("");
  const [materiality, setMateriality] = useState("1");
  const ids = useId();

  function reset() {
    setCode("");
    setName("");
    setStart("");
    setMateriality("1");
    create.reset();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const bp = parsed(materiality);
    create.mutate(
      {
        code: code.trim().toUpperCase(),
        name: name.trim(),
        start_date: start,
        non_business_dates: [],
        settings: Number.isNaN(bp) ? {} : { materiality_bp: bp },
      },
      {
        onSuccess: (fund) => {
          reset();
          onOpenChange(false);
          setFund(fund.code);
        },
      },
    );
  }

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="scrim" />
        <Dialog.Content className="dialog">
          <div className="dialog-head">
            <Dialog.Title>Add a fund</Dialog.Title>
          </div>
          <Dialog.Description className="muted">
            Its first business day is the first day whose files can be loaded. Every other setting starts at the
            engine&rsquo;s default and can be changed afterwards; AI starts off.
          </Dialog.Description>
          <form className="ad-form two" onSubmit={submit}>
            <label className="ad-field" htmlFor={`${ids}-c`}>
              Fund code
              <input
                id={`${ids}-c`}
                className="input mono"
                value={code}
                maxLength={32}
                required
                pattern="[A-Za-z0-9][A-Za-z0-9_\-]*"
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
            <label className="ad-field" htmlFor={`${ids}-n`}>
              Fund name
              <input
                id={`${ids}-n`}
                className="input"
                value={name}
                maxLength={200}
                required
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="ad-field" htmlFor={`${ids}-s`}>
              First business day
              <input
                id={`${ids}-s`}
                className="input"
                type="date"
                value={start}
                required
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label className="ad-field" htmlFor={`${ids}-m`}>
              Materiality, bp of NAV
              <input
                id={`${ids}-m`}
                className="input mono"
                type="number"
                min="0"
                step="any"
                value={materiality}
                onChange={(e) => setMateriality(e.target.value)}
              />
            </label>
            <p className="ad-span faint">Base currency: USD (the engine values every fund in US dollars).</p>
            <div className="ad-span">
              <FormError error={create.error} />
            </div>
            <div className="ad-dialog-actions ad-span">
              <Dialog.Close className="btn ghost" type="button" disabled={create.isPending}>
                Cancel
              </Dialog.Close>
              <button type="submit" className="btn primary" disabled={create.isPending}>
                {create.isPending ? "Adding…" : "Add fund"}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// --------------------------------------------------------------------------- the screen

export function FundsAdmin() {
  const { fund, fundsLoading } = useWorkspace();
  const detail = useAdminFund(fund?.code ?? null);
  const [adding, setAdding] = useState(false);

  let body;
  if (!fund) body = fundsLoading ? <Loading label="Loading funds" /> : <Empty>No fund is set up yet. Add the first.</Empty>;
  else if (detail.isPending) body = <Loading label="Loading the fund's settings" />;
  else if (detail.isError) body = <ErrorLine error={detail.error} retry={() => void detail.refetch()} />;
  else
    body = (
      <div className="ad-grid">
        <div className="ad-col">
          <SettingsPanel key={`${detail.data.code}-settings`} fund={detail.data} />
        </div>
        <div className="ad-col">
          <AiPanel key={`${detail.data.code}-ai-${detail.data.ai.provider ?? ""}-${detail.data.ai.enabled}`} fund={detail.data} />
          <CalendarPanel key={`${detail.data.code}-cal`} fund={detail.data} />
        </div>
      </div>
    );

  return (
    <>
      <div className="ad-block-head ad-top">
        <p className="muted">
          {fund ? (
            <>
              Working <span className="mono">{fund.code}</span>, {fund.name}. Choose another fund in the top bar.
            </>
          ) : (
            "No fund yet."
          )}
        </p>
        <button type="button" className="btn" onClick={() => setAdding(true)}>
          Add a fund
        </button>
      </div>
      {body}
      <AddFundDialog open={adding} onOpenChange={setAdding} />
    </>
  );
}
