import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

/*
 * Every test renders the whole app, and a screen's first content waits on a chain of mocked
 * requests (who am I, then the funds and the stored fund, then the day and its release, then
 * the screen's own data, then a case). The first render in each file is also cold: React and
 * every component run for the first time in that file's fresh module graph. Unloaded, a
 * file's first case opens in about 300 ms; under load that passed the library's default
 * 1 s budget for findBy and waitFor, and the first test failed on its first find though
 * nothing was wrong. Give every find a budget sized for a full app render; what each test
 * asserts is unchanged, and a real failure still fails, only a few seconds later.
 */
configure({ asyncUtilTimeout: 4000 });

/** jsdom has no matchMedia: answer "no preference" unless a test sets `mediaMatches`. */
export const mediaMatches = new Set<string>();

/**
 * Node's own (experimental) localStorage global shadows jsdom's and is undefined without a
 * storage file, so tests get a plain in-memory Storage instead.
 */
class MemoryStorage implements Storage {
  private items = new Map<string, string>();
  [name: string]: unknown;
  get length(): number {
    return this.items.size;
  }
  clear(): void {
    this.items.clear();
  }
  getItem(key: string): string | null {
    return this.items.get(key) ?? null;
  }
  key(index: number): string | null {
    return [...this.items.keys()][index] ?? null;
  }
  removeItem(key: string): void {
    this.items.delete(key);
  }
  setItem(key: string, value: string): void {
    this.items.set(key, String(value));
  }
}

for (const name of ["localStorage", "sessionStorage"] as const) {
  let usable = false;
  try {
    usable = typeof window[name]?.getItem === "function";
  } catch {
    usable = false;
  }
  if (!usable) Object.defineProperty(window, name, { configurable: true, value: new MemoryStorage() });
}

beforeEach(() => {
  mediaMatches.clear();
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: mediaMatches.has(query),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  for (const cookie of document.cookie.split(";")) {
    const name = cookie.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  }
});
