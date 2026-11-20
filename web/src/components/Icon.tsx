/**
 * Icons: a thin wrapper over Lucide (one set only), keeping the app's own short names so
 * every call site reads the same. Always decorative: the word beside an icon carries the
 * meaning, so status is never shown by an icon or a colour alone.
 *
 * The shape stays the same in every state; show a state with colour and the highlight
 * behind it. Stroke 2 inline (the default), 1.8 for navigation (`stroke={1.8}`). The size
 * comes from CSS (`svg.i`: 14px inline) unless `size` is given.
 */
import {
  ArrowDown,
  ArrowLeftRight,
  ArrowUp,
  ChartColumn,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  CircleCheck,
  Clock,
  Eye,
  FileCheck2,
  Info,
  Keyboard,
  KeyRound,
  Landmark,
  LayoutDashboard,
  Lock,
  LogOut,
  type LucideIcon,
  Minus,
  Moon,
  Plus,
  ScrollText,
  Search,
  Sun,
  TriangleAlert,
  Upload,
  User,
  X,
} from "lucide-react";

const ICONS = {
  check: Check,
  cross: X,
  warn: TriangleAlert,
  dot: Circle, // drawn filled, below
  ring: Circle,
  reclass: ArrowLeftRight,
  lock: Lock,
  clock: Clock,
  sun: Sun,
  moon: Moon,
  key: Keyboard, // the keyboard shortcuts
  up: ArrowUp,
  down: ArrowDown,
  flat: Minus,
  sort: ChevronDown,
  eye: Eye,
  user: User,
  chevron: ChevronDown,
  next: ChevronRight,
  out: LogOut,
  search: Search,
  info: Info,
  plus: Plus,
  admin: KeyRound,
  // The screens, for the navigation.
  overview: LayoutDashboard,
  upload: Upload,
  cases: CircleCheck,
  signoff: FileCheck2,
  mi: ChartColumn,
  audit: ScrollText,
  funds: Landmark,
} as const satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof ICONS;

export function Icon({
  name,
  className = "",
  size,
  stroke = 2,
}: {
  name: IconName;
  className?: string;
  /** Pixel size; without it, CSS decides (14px inline). */
  size?: number;
  /** Stroke width: 2 inline, 1.8 for navigation. */
  stroke?: number;
}) {
  const Glyph = ICONS[name];
  const solid = name === "dot";
  return (
    <Glyph
      className={`i i-${name}${solid ? " solid" : ""} ${className}`.trim()}
      aria-hidden="true"
      focusable="false"
      strokeWidth={solid ? 0 : stroke}
      fill={solid ? "currentColor" : "none"}
      {...(size ? { width: size, height: size } : {})}
    />
  );
}
