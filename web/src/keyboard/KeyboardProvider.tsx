/**
 * The keyboard framework (spec section 10, "Keyboard").
 *
 * Screens register shortcuts with `useShortcut`; one listener on the window dispatches
 * them. Keys are written as the key's own name ("?", "a", "Enter", "Escape", "ArrowDown"),
 * "mod+k" for Ctrl or Cmd with a key, and sequences with a space ("g o": press g, then o
 * within 1.5 seconds).
 *
 * Shortcuts never fire while the person is typing (focus in an input, textarea, select or
 * editable element), inside an open dialog or menu (which handles its own keys, Esc
 * included), or with Alt held; the one exception is a shortcut registered `whileTyping`
 * (Ctrl+K for the command palette). Esc in a text field leaves the field, so the screen's
 * keys work again. The help dialog lists whatever is registered.
 *
 * The command palette's actions come from here too: a shortcut registered with `palette`
 * is also an action, and `useCommand` registers an action with no key of its own. Both
 * exist only while `enabled`, so the palette offers only what the person may run now (the
 * server still checks every request).
 */
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

export const SEQUENCE_TIMEOUT_MS = 1500;

export interface ShortcutInfo {
  keys: string;
  description: string;
  group: string;
}

interface Registered extends ShortcutInfo {
  id: number;
  handler: (event: KeyboardEvent) => void;
  /** Whether this press is the shortcut's; when false the key keeps its ordinary meaning. */
  when?: (event: KeyboardEvent) => boolean;
  /** Fires even while the person is typing in a field. */
  whileTyping?: boolean;
}

/** An action the command palette can run. */
export interface CommandInfo {
  id: number;
  label: string;
  group: string;
  /** The action's own shortcut, shown beside it, if it has one. */
  keys?: string;
  /** Other words it can be found by. */
  keywords?: string;
  run: () => void;
}

const NON_TEXT_INPUTS = new Set(["button", "checkbox", "radio", "submit", "reset", "range", "color", "file", "image"]);

/** Whether keys pressed now are text for a field rather than commands. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  if (target instanceof HTMLInputElement) return !NON_TEXT_INPUTS.has(target.type);
  if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
  if (target instanceof HTMLElement && (target.isContentEditable || target.getAttribute("contenteditable") === "true")) {
    return true;
  }
  return target.closest('[contenteditable="true"]') != null;
}

/** A field whose text Esc can leave (not a select, whose Esc closes its own list). */
function isTextField(target: EventTarget | null): target is HTMLInputElement | HTMLTextAreaElement {
  return (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) && isTypingTarget(target);
}

function insideLayer(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest('[role="dialog"], [role="alertdialog"], [role="menu"]') != null;
}

/** The name a key event is registered under, or null for keys that are never shortcuts. */
export function keyToken(event: KeyboardEvent): string | null {
  if (event.altKey || event.isComposing) return null;
  const key = event.key;
  if (!key || key === "Shift" || key === "Control" || key === "Meta" || key === "Alt") return null;
  if (event.ctrlKey || event.metaKey) return `mod+${key.toLowerCase()}`;
  return key; // printable keys as typed ("?", "g"), named keys by name ("Enter", "Escape")
}

class Registry {
  private items = new Map<number, Registered>();
  private commands = new Map<number, CommandInfo>();
  private next = 1;
  private listeners = new Set<() => void>();
  private snapshot: ShortcutInfo[] = [];
  private commandSnapshot: CommandInfo[] = [];

  add(item: Omit<Registered, "id">): number {
    const id = this.next++;
    this.items.set(id, { ...item, id });
    this.changed();
    return id;
  }

  remove(id: number): void {
    if (this.items.delete(id)) this.changed();
  }

  addCommand(command: Omit<CommandInfo, "id">): number {
    const id = this.next++;
    this.commands.set(id, { ...command, id });
    this.commandsChanged();
    return id;
  }

  removeCommand(id: number): void {
    if (this.commands.delete(id)) this.commandsChanged();
  }

  /**
   * The most recently registered shortcut for `keys` that takes this press (a screen's
   * binding wins over the shell's). While typing, only shortcuts registered `whileTyping`.
   */
  find(keys: string, event?: KeyboardEvent, typing = false): Registered | undefined {
    let found: Registered | undefined;
    for (const item of this.items.values()) {
      if (typing && !item.whileTyping) continue;
      if (item.keys === keys && (!event || !item.when || item.when(event))) found = item;
    }
    return found;
  }

  isPrefix(token: string): boolean {
    for (const item of this.items.values()) if (item.keys.startsWith(`${token} `)) return true;
    return false;
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = () => this.snapshot;

  getCommands = () => this.commandSnapshot;

  private changed(): void {
    const seen = new Set<string>();
    const list: ShortcutInfo[] = [];
    for (const { keys, description, group } of this.items.values()) {
      const key = `${group}|${keys}`;
      if (!seen.has(key)) {
        seen.add(key);
        list.push({ keys, description, group });
      }
    }
    this.snapshot = list;
    this.notify();
  }

  private commandsChanged(): void {
    this.commandSnapshot = [...this.commands.values()];
    this.notify();
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}

const KeyboardContext = createContext<Registry | null>(null);

export function KeyboardProvider({ children }: { children: ReactNode }) {
  const [registry] = useState(() => new Registry());
  const pending = useRef<{ token: string; timer: ReturnType<typeof setTimeout> } | null>(null);

  useEffect(() => {
    const clearPending = () => {
      if (pending.current) clearTimeout(pending.current.timer);
      pending.current = null;
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || insideLayer(event.target)) {
        clearPending();
        return;
      }
      if (isTypingTarget(event.target)) {
        clearPending();
        const token = keyToken(event);
        const match = token ? registry.find(token, event, true) : undefined;
        if (match) {
          event.preventDefault();
          match.handler(event);
        } else if (token === "Escape" && isTextField(event.target)) {
          event.target.blur(); // leave the field, so the screen's keys work again
        }
        return;
      }
      const token = keyToken(event);
      if (token == null) return;

      if (pending.current) {
        const sequence = `${pending.current.token} ${token}`;
        clearPending();
        const match = registry.find(sequence, event);
        if (match) {
          event.preventDefault();
          match.handler(event);
          return;
        }
      }
      if (registry.isPrefix(token)) {
        event.preventDefault();
        pending.current = { token, timer: setTimeout(clearPending, SEQUENCE_TIMEOUT_MS) };
        return;
      }
      const match = registry.find(token, event);
      if (match) {
        event.preventDefault();
        match.handler(event);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      clearPending();
    };
  }, [registry]);

  return <KeyboardContext.Provider value={registry}>{children}</KeyboardContext.Provider>;
}

function useRegistry(): Registry {
  const registry = useContext(KeyboardContext);
  if (!registry) throw new Error("Keyboard shortcuts need a KeyboardProvider");
  return registry;
}

export interface ShortcutOptions {
  description: string;
  group?: string;
  /** Register only while true (for example, only when the person may act). */
  enabled?: boolean;
  /**
   * Take a press only when this returns true (for example, Enter only when focus is not on
   * a button or link); otherwise the key does what it ordinarily does.
   */
  when?: (event: KeyboardEvent) => boolean;
  /**
   * Also offer the shortcut as an action in the command palette: `true` uses its
   * description as the label, a string gives another label.
   */
  palette?: boolean | string;
  /** Fire even while the person is typing in a field (only Ctrl+K should). */
  whileTyping?: boolean;
}

/** Register a shortcut for as long as the calling component is mounted (and `enabled`). */
export function useShortcut(keys: string, handler: (event: KeyboardEvent) => void, options: ShortcutOptions): void {
  const registry = useRegistry();
  const { description, group = "General", enabled = true, when, palette, whileTyping = false } = options;
  const handlerRef = useRef(handler);
  const whenRef = useRef(when);

  useEffect(() => {
    handlerRef.current = handler;
    whenRef.current = when;
  });

  useEffect(() => {
    if (!enabled) return;
    const id = registry.add({
      keys,
      description,
      group,
      whileTyping,
      handler: (event) => handlerRef.current(event),
      when: (event) => whenRef.current?.(event) ?? true,
    });
    return () => registry.remove(id);
  }, [registry, keys, description, group, enabled, whileTyping]);

  const label = palette === true ? description : palette || null;
  useEffect(() => {
    if (!enabled || !label) return;
    const key = keys.split(" ").pop() ?? keys;
    const id = registry.addCommand({
      label,
      group,
      keys,
      // The palette has no key press to pass on; the handler gets one naming its key.
      run: () => handlerRef.current(new KeyboardEvent("keydown", { key })),
    });
    return () => registry.removeCommand(id);
  }, [registry, label, group, keys, enabled]);
}

export interface CommandOptions {
  group?: string;
  /** Offer the action only while true (for example, only to a role that may run it). */
  enabled?: boolean;
  /** Other words the action can be found by in the palette. */
  keywords?: string;
  /** A shortcut that does the same, shown beside the action. */
  keys?: string;
}

/**
 * Register an action for the command palette (one with no key of its own) for as long as
 * the calling component is mounted and `enabled`.
 */
export function useCommand(label: string, run: () => void, options: CommandOptions = {}): void {
  const registry = useRegistry();
  const { group = "General", enabled = true, keywords, keys } = options;
  const runRef = useRef(run);

  useEffect(() => {
    runRef.current = run;
  });

  useEffect(() => {
    if (!enabled) return;
    const id = registry.addCommand({ label, group, keywords, keys, run: () => runRef.current() });
    return () => registry.removeCommand(id);
  }, [registry, label, group, keywords, keys, enabled]);
}

/** Every action the command palette can run now, in the order they were registered. */
export function useCommands(): CommandInfo[] {
  const registry = useRegistry();
  return useSyncExternalStore(registry.subscribe, registry.getCommands, registry.getCommands);
}

/** Every registered shortcut, for the help dialog. */
export function useRegisteredShortcuts(): ShortcutInfo[] {
  const registry = useRegistry();
  return useSyncExternalStore(registry.subscribe, registry.getSnapshot, registry.getSnapshot);
}

/** Group shortcuts for display, keeping the order groups were first registered in. */
export function useGroupedShortcuts(): [string, ShortcutInfo[]][] {
  const list = useRegisteredShortcuts();
  return useMemo(() => {
    const groups = new Map<string, ShortcutInfo[]>();
    for (const item of list) groups.set(item.group, [...(groups.get(item.group) ?? []), item]);
    return [...groups.entries()];
  }, [list]);
}
