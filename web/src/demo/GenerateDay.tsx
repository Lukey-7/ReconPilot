/**
 * The demo's stand-in for uploading: generate the fund's next business day from the same
 * synthetic sequence. The server stores and validates its files exactly as an upload and
 * queues its run; the screen then follows the run like any other. Days are still worked in
 * order, so the next day can be generated only once the latest one is signed off.
 */
import { Link } from "react-router";

import { ApiError } from "../api/client";
import { useGenerateNextDay } from "../api/queries";
import type { FundSummary, User } from "../api/types";
import { Icon } from "../components/Icon";
import { dayLabel } from "../format";
import { useWorkspace } from "../shell/workspace";

export function GenerateDay({ fund, user }: { fund: FundSummary; user: User }) {
  const { days, setDay, href } = useWorkspace();
  const generate = useGenerateNextDay(fund.code);
  const next = days?.next_day ?? null;
  const latest = days?.days[0] ?? null;
  const mayAct = user.role === "analyst" || user.role === "approver";

  return (
    <div className="up-order demo-generate">
      <Icon name="clock" />
      <div>
        <p className="up-order-title">In the demo, days are generated rather than uploaded.</p>
        <p>
          Each day’s files come from the same synthetic sequence. They are checked like an upload and run by the same
          engine, with breaks carried from the day before.
        </p>
        {next && mayAct && (
          <p className="up-order-act">
            <button
              type="button"
              className="btn primary"
              disabled={generate.isPending}
              onClick={() => generate.mutate(undefined, { onSuccess: (result) => setDay(result.as_of) })}
            >
              {generate.isPending ? "Generating…" : `Generate ${dayLabel(next)}`}
            </button>
          </p>
        )}
        {!next && latest && latest.status !== "signed_off" && (
          <p className="up-order-act">
            <span className="muted">Sign off {dayLabel(latest.as_of)} to generate the next business day.</span>{" "}
            <Link className="btn" to={href("/signoff", { day: latest.as_of })}>
              Open the sign-off
            </Link>
          </p>
        )}
        {next && !mayAct && <p className="faint">Viewers can follow the days but cannot generate them.</p>}
        {generate.isError && (
          <p className="state-line error" role="alert">
            <Icon name="warn" />
            <span>
              {generate.error instanceof ApiError ? generate.error.message : "The day could not be generated. Try again."}
            </span>
          </p>
        )}
      </div>
    </div>
  );
}
