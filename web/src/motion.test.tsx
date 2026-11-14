import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReleaseBadge, type ReleaseState } from "./components/Labels";
import { TWEEN_MS, useChangeCount, useTween } from "./motion";
import { mediaMatches } from "./test/setup";

function Tweened({ value }: { value: number | null }) {
  const shown = useTween(value);
  return <span data-testid="fig">{shown == null ? "none" : shown.toFixed(2)}</span>;
}

function shown(): string {
  return screen.getByTestId("fig").textContent ?? "";
}

describe("figure tweens", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the first value at once, then eases to a new one and settles on it exactly", () => {
    const { rerender } = render(<Tweened value={100} />);
    expect(shown()).toBe("100.00");
    rerender(<Tweened value={200} />);
    act(() => {
      vi.advanceTimersByTime(TWEEN_MS / 2);
    });
    const midway = Number(shown());
    expect(midway).toBeGreaterThan(100);
    expect(midway).toBeLessThan(200);
    act(() => {
      vi.advanceTimersByTime(TWEEN_MS);
    });
    expect(shown()).toBe("200.00");
  });

  it("never tweens to or from a missing figure", () => {
    const { rerender } = render(<Tweened value={null} />);
    expect(shown()).toBe("none");
    rerender(<Tweened value={50} />);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(shown()).toBe("50.00");
    rerender(<Tweened value={null} />);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(shown()).toBe("none");
  });

  it("shows the new value at once under reduced motion", () => {
    mediaMatches.add("(prefers-reduced-motion: reduce)");
    const { rerender } = render(<Tweened value={100} />);
    rerender(<Tweened value={200} />);
    expect(shown()).toBe("200.00");
  });
});

function Status({ state, scope, ready = true }: { state: ReleaseState; scope: string; ready?: boolean }) {
  const changes = useChangeCount(state, scope, ready);
  return (
    <>
      <span data-testid="count">{changes}</span>
      <ReleaseBadge key={changes} state={state} changed={changes > 0} />
    </>
  );
}

describe("the release status changing", () => {
  it("pulses when the status moves in place, not on first show or on another day", () => {
    const { rerender, container } = render(<Status state="blocked" scope="GEF1|2026-11-10" />);
    const badge = () => container.querySelector(".release-badge");
    expect(badge()).not.toHaveClass("release-changed");
    rerender(<Status state="ready" scope="GEF1|2026-11-10" />);
    expect(screen.getByTestId("count")).toHaveTextContent("1");
    expect(badge()).toHaveClass("release-changed");
    expect(badge()).toHaveTextContent("Ready to sign off");
    rerender(<Status state="signedOff" scope="GEF1|2026-11-10" />);
    expect(screen.getByTestId("count")).toHaveTextContent("2");
    // Another day's status is not a change.
    rerender(<Status state="blocked" scope="GEF1|2026-11-11" />);
    expect(screen.getByTestId("count")).toHaveTextContent("0");
    expect(badge()).not.toHaveClass("release-changed");
  });

  it("ignores what it sees while still loading", () => {
    const { rerender } = render(<Status state="blocked" scope="A" ready={false} />);
    rerender(<Status state="ready" scope="A" />);
    expect(screen.getByTestId("count")).toHaveTextContent("0");
  });
});
