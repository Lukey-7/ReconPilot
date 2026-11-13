/** A key sequence such as "g o", shown as separate keys. Hidden from assistive tech: the action's name says it. */
export function Kbd({ keys, className = "" }: { keys: string; className?: string }) {
  return (
    <span className={`kbd-hint ${className}`.trim()} aria-hidden="true">
      {keys.split(" ").map((k, i) => (
        <kbd key={i}>{k === "Escape" ? "Esc" : k}</kbd>
      ))}
    </span>
  );
}
