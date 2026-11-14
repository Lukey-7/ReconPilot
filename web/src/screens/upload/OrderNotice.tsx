/**
 * Why a day cannot take files, in plain words, before anyone tries (from `GET .../intake`).
 *
 * Days are worked in order: a business day's files are loaded only once the previous
 * business day is signed off. The notice names the day that is holding things up, its
 * status, and the way to it. The server enforces the same rule; this only says it first.
 */
import { Link } from "react-router";

import type { Intake, IntakeBlock } from "../../api/types";
import { Icon } from "../../components/Icon";
import { dayLabel } from "../../format";
import { useWorkspace } from "../../shell/workspace";
import { dayStatusPhrase } from "../../vocabulary";

/** Reasons this notice explains; a signed-off or running day is shown by the screen itself. */
export const ORDER_BLOCKS: ReadonlySet<string> = new Set([
  "UPLOADS_OFF",
  "BEFORE_START",
  "NOT_BUSINESS_DAY",
  "PREVIOUS_NOT_LOADED",
  "PREVIOUS_NOT_SIGNED_OFF",
]);

function PreviousDayLink({ block }: { block: IntakeBlock }) {
  const { href, setDay } = useWorkspace();
  const day = block.day;
  if (!day) return null;
  const label = dayLabel(day);
  if (block.code === "PREVIOUS_NOT_SIGNED_OFF" && block.day_status === "ready") {
    return (
      <Link className="btn" to={href("/signoff", { day })}>
        Open the sign-off for {label}
      </Link>
    );
  }
  if (block.code === "PREVIOUS_NOT_SIGNED_OFF" && block.day_status === "signed_off") return null;
  return (
    <button type="button" className="btn" onClick={() => setDay(day)}>
      Go to {label}
    </button>
  );
}

export function OrderNotice({ intake, fundCode }: { intake: Intake; fundCode: string }) {
  const block = intake.blocked;
  if (!block || !ORDER_BLOCKS.has(block.code)) return null;
  const target = dayLabel(intake.as_of);
  const other = block.day ? dayLabel(block.day) : "";

  let title: string;
  let detail: string;
  switch (block.code) {
    case "PREVIOUS_NOT_SIGNED_OFF":
      title = `${other} is not signed off yet.`;
      detail =
        `Days are worked in order, so ${target}’s files can be loaded only after that day’s NAV is signed off. ` +
        `It is ${dayStatusPhrase(block.day_status)}.`;
      break;
    case "PREVIOUS_NOT_LOADED":
      title = `${other} has no files yet.`;
      detail = `Days are worked in order: load, run and sign off ${other} before ${target}.`;
      break;
    case "BEFORE_START":
      title = `${target} is before ${fundCode}’s first business day.`;
      detail = `${fundCode} starts on ${other}; there is nothing to load before it.`;
      break;
    case "NOT_BUSINESS_DAY":
      title = `${target} is not a business day for ${fundCode}.`;
      detail = "It is a weekend or one of the fund’s non-business days, so it has no files to load.";
      break;
    default:
      title = "Files cannot be loaded here.";
      detail = block.message;
  }

  return (
    <div className="up-order notice" role="status">
      <Icon name={block.code === "PREVIOUS_NOT_SIGNED_OFF" || block.code === "PREVIOUS_NOT_LOADED" ? "lock" : "warn"} />
      <div>
        <p className="up-order-title">{title}</p>
        <p>{detail}</p>
        {(block.code === "PREVIOUS_NOT_SIGNED_OFF" || block.code === "PREVIOUS_NOT_LOADED") && (
          <p className="up-order-act">
            <PreviousDayLink block={block} />
          </p>
        )}
        {block.code === "BEFORE_START" && block.day && (
          <p className="up-order-act">
            <StartDayButton day={block.day} />
          </p>
        )}
      </div>
    </div>
  );
}

function StartDayButton({ day }: { day: string }) {
  const { setDay } = useWorkspace();
  return (
    <button type="button" className="btn" onClick={() => setDay(day)}>
      Go to {dayLabel(day)}
    </button>
  );
}
