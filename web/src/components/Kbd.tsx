/**
 * A key sequence such as "g o" or "mod+k", shown as separate keys ("mod" is Ctrl). Hidden
 * from assistive tech: the action's name says it.
 */
export function keyNames(keys: string): string[] {
  return keys.split(" ").flatMap((k) => {
    if (k === "Escape") return ["Esc"];
    if (k === "ArrowDown") return ["↓"];
    if (k === "ArrowUp") return ["↑"];
    if (k.startsWith("mod+")) return ["Ctrl", k.slice(4).toUpperCase()];
    return [k];
  });
}

export function Kbd({ keys, className = "" }: { keys: string; className?: string }) {
  return (
    <span className={`kbd-hint ${className}`.trim()} aria-hidden="true">
      {keyNames(keys).map((k, i) => (
        <kbd key={i}>{k}</kbd>
      ))}
    </span>
  );
}
