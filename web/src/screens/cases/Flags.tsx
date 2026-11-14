/**
 * A case's flags as labelled tags (material, escalated, past SLA, AI disagrees): words, not
 * letters or colour, so a flag reads the same to everyone. Flags are labels, not buttons.
 */
import type { ReactNode } from "react";

import type { QueueCase } from "../../api/types";
import { Icon, type IconName } from "../../components/Icon";
import { FLAGS } from "../../vocabulary";

type FlagKey = keyof typeof FLAGS;

const ICONS: Record<FlagKey, IconName> = { material: "warn", escalated: "up", sla: "clock", ai: "eye" };

export function caseFlags(c: Pick<QueueCase, "material" | "escalated" | "sla_breached" | "ai_flag">): FlagKey[] {
  const flags: FlagKey[] = [];
  if (c.material) flags.push("material");
  if (c.escalated) flags.push("escalated");
  if (c.sla_breached) flags.push("sla");
  if (c.ai_flag) flags.push("ai");
  return flags;
}

export function FlagTag({ flag, children }: { flag: FlagKey; children?: ReactNode }) {
  return (
    <span className={`tag wb-flag wb-flag-${flag}`} data-flag={flag}>
      <Icon name={ICONS[flag]} />
      {children ?? FLAGS[flag]}
    </span>
  );
}

export function Flags({ c }: { c: Pick<QueueCase, "material" | "escalated" | "sla_breached" | "ai_flag"> }) {
  const flags = caseFlags(c);
  if (!flags.length) return null;
  return (
    <span className="wb-flags">
      {flags.map((f) => (
        <FlagTag key={f} flag={f} />
      ))}
    </span>
  );
}
