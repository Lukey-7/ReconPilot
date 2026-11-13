/**
 * Small stroked glyphs (16 by 16). Always decorative: the word beside an icon carries
 * the meaning, so status is never shown by an icon or a colour alone.
 */
const PATHS = {
  check: <path d="M3.2 8.6l3 3 6.6-7.2" />,
  cross: <path d="M4.2 4.2l7.6 7.6M11.8 4.2l-7.6 7.6" />,
  warn: (
    <>
      <path d="M8 2.2l6.4 11.3H1.6z" />
      <path d="M8 6.4v3.4M8 11.8v.1" />
    </>
  ),
  dot: <circle cx="8" cy="8" r="3.6" fill="currentColor" stroke="none" />,
  ring: <circle cx="8" cy="8" r="5" />,
  reclass: <path d="M2.8 6h9.4l-2.4-2.4M13.2 10H3.8l2.4 2.4" />,
  lock: (
    <>
      <rect x="3.2" y="7.2" width="9.6" height="6.6" rx="1" />
      <path d="M5.4 7.2V5.2a2.6 2.6 0 015.2 0v2" />
    </>
  ),
  clock: (
    <>
      <circle cx="8" cy="8" r="5.8" />
      <path d="M8 4.8V8l2.2 1.6" />
    </>
  ),
  sun: (
    <>
      <circle cx="8" cy="8" r="3" />
      <path d="M8 1.6v1.6M8 12.8v1.6M1.6 8h1.6M12.8 8h1.6M3.5 3.5l1.1 1.1M11.4 11.4l1.1 1.1M3.5 12.5l1.1-1.1M11.4 4.6l1.1-1.1" />
    </>
  ),
  moon: <path d="M13 9.6A5.6 5.6 0 016.4 3a5.6 5.6 0 106.6 6.6z" />,
  key: (
    <>
      <rect x="1.6" y="4.2" width="12.8" height="7.6" rx="1.2" />
      <path d="M4.2 6.8h.1M6.6 6.8h.1M9 6.8h.1M11.4 6.8h.1M5 9.4h6" />
    </>
  ),
  up: <path d="M8 3.4l5.2 7.6H2.8z" fill="currentColor" stroke="none" />,
  down: <path d="M8 12.6L2.8 5h10.4z" fill="currentColor" stroke="none" />,
  flat: <path d="M3 8h10" />,
  sort: <path d="M4 6l4 4 4-4" />,
  eye: (
    <>
      <path d="M1.6 8s2.4-4.4 6.4-4.4S14.4 8 14.4 8 12 12.4 8 12.4 1.6 8 1.6 8z" />
      <circle cx="8" cy="8" r="1.9" />
    </>
  ),
  user: (
    <>
      <circle cx="8" cy="5.6" r="2.6" />
      <path d="M2.8 13.6c.6-2.6 2.7-4 5.2-4s4.6 1.4 5.2 4" />
    </>
  ),
  chevron: <path d="M4 6l4 4 4-4" />,
  out: <path d="M9.6 3H3.2v10h6.4M7 8h6.8M11.4 5.6L13.8 8l-2.4 2.4" />,
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  return (
    <svg className={`i ${className}`.trim()} viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      {PATHS[name]}
    </svg>
  );
}
