/**
 * The sticky NAV strip shown on every screen (Night desk's rail): NAV, NAV per share and
 * its movement, the day's one release status with its reasons, and the way to sign-off.
 *
 * Figures come from the day record (`GET .../days/{as_of}`) and the status from the
 * release route (`GET .../release`), which the server computes identically for everyone.
 * The strip never works a status out for itself.
 */
import * as Popover from "@radix-ui/react-popover";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import { useDay, useRelease } from "../api/queries";
import { Icon } from "../components/Icon";
import { Kbd } from "../components/Kbd";
import { ReleaseBadge, releaseState } from "../components/Labels";
import { MISSING, money, perShare, signedPercent, timestamp } from "../format";
import { RELEASE_LABELS, releaseReasonLabel } from "../vocabulary";
import { useWorkspace } from "./workspace";

function Movement({ movement, prior }: { movement: number | null | undefined; prior: number | null | undefined }) {
  if (movement == null || !prior) return <span className="mv faint">No prior NAV</span>;
  const direction = movement > 0 ? "up" : movement < 0 ? "down" : "flat";
  const word = { up: "Up", down: "Down", flat: "Unchanged" }[direction];
  return (
    <span className="mv">
      <Icon name={direction} />
      <span className="sr-only">{word} </span>
      <span className="fig">{signedPercent(movement)}</span>
      <span className="faint"> on {perShare(prior)}</span>
    </span>
  );
}

export function NavStrip() {
  const { fund, asOf, href, daysLoading } = useWorkspace();
  const code = fund?.code ?? null;
  const day = useDay(code, asOf);
  const release = useRelease(code, asOf);

  if (!fund) return null;
  if (!asOf) {
    return (
      <section className="strip strip-empty" aria-label="NAV and release status">
        <p className="muted">{daysLoading ? "Loading business days…" : `No business day has been loaded for ${fund.name} yet.`}</p>
      </section>
    );
  }

  const noFiles = day.error instanceof ApiError && day.error.status === 404;
  const nav = day.data?.nav ?? null;
  const signedOff = day.data?.status === "signed_off" || release.data?.signed_off === true;
  const state = releaseState(release.data, signedOff);
  const reasons = release.data?.reasons ?? [];
  const first = reasons[0];

  let why: string;
  if (release.isPending) why = "Checking release conditions…";
  else if (release.isError) why = release.error instanceof ApiError ? release.error.message : "Release status unavailable.";
  else if (signedOff) why = `by ${day.data?.signed_off_by ?? "an approver"}, ${timestamp(day.data?.signed_off_at)}`;
  else if (state === "ready") why = "Every release condition is met.";
  else why = first ? first.message : "Release conditions are not met.";

  return (
    <section className="strip" aria-label="NAV and release status">
      <div className="strip-cell">
        <span className="lbl">NAV, {fund.base_currency}</span>
        <span className="big fig" data-testid="strip-nav">
          {noFiles ? MISSING : money(nav?.nav)}
        </span>
        {noFiles ? <span className="mv faint">No files loaded</span> : !nav && !day.isPending && <span className="mv faint">Not run yet</span>}
      </div>
      <div className="strip-cell">
        <span className="lbl">NAV per share</span>
        <span className="big fig" data-testid="strip-nps">
          {perShare(nav?.nav_per_share)}
        </span>
        {nav && <Movement movement={nav.detail?.movement} prior={nav.prior_nav_per_share} />}
      </div>
      <div className="lamp" data-state={state} aria-live="polite">
        {release.isPending ? (
          <span className="release-badge release-pending">{MISSING}</span>
        ) : (
          <ReleaseBadge state={state} />
        )}
        <p className="why">
          {why}
          {!signedOff && reasons.length > 1 && <span className="faint"> and {reasons.length - 1} more</span>}
        </p>
        {!signedOff && reasons.length > 0 && (
          <Popover.Root>
            <Popover.Trigger className="btn ghost reasons-btn">
              {reasons.length === 1 ? "Reason" : `All ${reasons.length} reasons`}
              <Icon name="chevron" />
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content className="popover reasons" align="start" sideOffset={6}>
                <p className="popover-title">{RELEASE_LABELS.blocked}: why</p>
                <ul>
                  {reasons.map((r, i) => (
                    <li key={`${r.code}-${i}`}>
                      <span className="reason-code">{releaseReasonLabel(r.code)}</span>
                      <span>{r.message}</span>
                    </li>
                  ))}
                </ul>
                <Popover.Close className="btn ghost popover-close" aria-label="Close">
                  <Icon name="cross" />
                </Popover.Close>
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        )}
      </div>
      <div className="go">
        <Link className="btn" to={href("/signoff")}>
          {signedOff ? "View sign-off" : "Open sign-off"}
          <Kbd keys="g s" />
        </Link>
      </div>
    </section>
  );
}
