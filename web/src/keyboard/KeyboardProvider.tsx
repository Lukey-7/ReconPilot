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
 * included), or with Alt held. The help dialog lists whatever is registered.
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
  private next = 1;
  private listeners = new Set<() => void>();
  private snapshot: ShortcutInfo[] = [];

  add(item: Omit<Registered, "id">): number {
    const id = this.next++;
    this.items.set(id, { ...item, id });
    this.changed();
    return id;
  }

  update(id: number, handler: Registered["handler"]): void {
    const item = this.items.get(id);
    if (item) item.handler = handler;
  }

  remove(id: number): void {
    if (this.items.delete(id)) this.changed();
  }

  /**
   * The most recently registered shortcut for `keys` that takes this press (a screen's
   * binding wins over the shell's).
   */
  find(keys: string, event?: KeyboardEvent): Registered | undefined {
    let found: Registered | undefined;
    for (const item of this.items.values()) {
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
      if (event.defaultPrevented || isTypingTarget(event.target) || insideLayer(event.target)) {
        clearPending();
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
}

/** Register a shortcut for as long as the calling component is mounted (and `enabled`). */
export function useShortcut(keys: string, handler: (event: KeyboardEvent) => void, options: ShortcutOptions): void {
  const registry = useRegistry();
  const { description, group = "General", enabled = true, when } = options;
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
      handler: (event) => handlerRef.current(event),
      when: (event) => whenRef.current?.(event) ?? true,
    });
    return () => registry.remove(id);
  }, [registry, keys, description, group, enabled]);
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

