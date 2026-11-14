import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { mockApi } from "../test/mockApi";
import { location, renderApp, signedInRoutes } from "../test/render";
import { KeyboardProvider, SEQUENCE_TIMEOUT_MS, isTypingTarget, useShortcut } from "./KeyboardProvider";

function Probe({ onA, onGo }: { onA: () => void; onGo: () => void }) {
  useShortcut("a", onA, { description: "Approve" });
  useShortcut("g o", onGo, { description: "Go" });
  const [text, setText] = useState("");
  return (
    <>
      <input aria-label="Note" value={text} onChange={(e) => setText(e.target.value)} />
      <textarea aria-label="Long note" />
      <div role="dialog" aria-label="A dialog">
        <button type="button">Inside</button>
      </div>
    </>
  );
}

function renderProbe() {
  const onA = vi.fn();
  const onGo = vi.fn();
  render(
    <KeyboardProvider>
      <Probe onA={onA} onGo={onGo} />
    </KeyboardProvider>,
  );
  return { onA, onGo };
}

describe("keyboard framework", () => {
  it("runs single keys and sequences", () => {
    const { onA, onGo } = renderProbe();
    fireEvent.keyDown(document.body, { key: "a" });
    expect(onA).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document.body, { key: "g" });
    fireEvent.keyDown(document.body, { key: "o" });
    expect(onGo).toHaveBeenCalledTimes(1);
  });

  it("never fires while typing", async () => {
    const { onA, onGo } = renderProbe();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Note"), "a go");
    await user.type(screen.getByLabelText("Long note"), "ag o");
    expect(onA).not.toHaveBeenCalled();
    expect(onGo).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Note")).toHaveValue("a go");
  });

  it("leaves keys inside a dialog to the dialog, and ignores modified keys", () => {
    const { onA } = renderProbe();
    fireEvent.keyDown(screen.getByRole("button", { name: "Inside" }), { key: "a" });
    fireEvent.keyDown(document.body, { key: "a", altKey: true });
    fireEvent.keyDown(document.body, { key: "a", ctrlKey: true });
    expect(onA).not.toHaveBeenCalled();
  });

  it("leaves a key to the focused control when the shortcut declines it", () => {
    const onEnter = vi.fn();
    function EnterProbe() {
      useShortcut("Enter", onEnter, { description: "Open", when: (e) => !(e.target instanceof HTMLButtonElement) });
      return <button type="button">A button</button>;
    }
    render(
      <KeyboardProvider>
        <EnterProbe />
      </KeyboardProvider>,
    );
    const onButton = fireEvent.keyDown(screen.getByRole("button", { name: "A button" }), { key: "Enter" });
    expect(onEnter).not.toHaveBeenCalled();
    expect(onButton).toBe(true); // not prevented: the button still clicks
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(onEnter).toHaveBeenCalledTimes(1);
  });

  it("forgets a half-typed sequence after the timeout", () => {
    vi.useFakeTimers();
    try {
      const { onGo } = renderProbe();
      fireEvent.keyDown(document.body, { key: "g" });
      act(() => {
        vi.advanceTimersByTime(SEQUENCE_TIMEOUT_MS + 10);
      });
      fireEvent.keyDown(document.body, { key: "o" });
      expect(onGo).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("knows what counts as typing", () => {
    const input = document.createElement("input");
    const checkbox = Object.assign(document.createElement("input"), { type: "checkbox" });
    const select = document.createElement("select");
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    expect(isTypingTarget(input)).toBe(true);
    expect(isTypingTarget(select)).toBe(true);
    expect(isTypingTarget(editable)).toBe(true);
    expect(isTypingTarget(checkbox)).toBe(false);
    expect(isTypingTarget(document.body)).toBe(false);
  });
});

describe("shell shortcuts", () => {
  it("g then q, s and o move between screens, keeping the fund and day", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    await screen.findByRole("heading", { name: "Morning overview" });
    const user = userEvent.setup();
    await user.keyboard("gq");
    expect(await screen.findByRole("heading", { name: "Cases" })).toBeInTheDocument();
    expect(location()).toBe("/cases?fund=GEF1&day=2026-11-10");
    await user.keyboard("gs");
    expect(await screen.findByRole("heading", { name: "NAV sign-off" })).toBeInTheDocument();
    await user.keyboard("go");
    expect(await screen.findByRole("heading", { name: "Morning overview" })).toBeInTheDocument();
  });

  it("? opens the shortcuts dialog listing the registered shortcuts, and Esc closes it", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    await screen.findByRole("heading", { name: "Morning overview" });
    const user = userEvent.setup();
    await user.keyboard("?");
    const dialog = await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(within(dialog).getByText("Go to the overview")).toBeInTheDocument();
    expect(within(dialog).getByText("Go to the cases")).toBeInTheDocument();
    expect(within(dialog).getByText("Go to sign-off")).toBeInTheDocument();
    expect(within(dialog).getByText("Show keyboard shortcuts")).toBeInTheDocument();

    // Shortcuts do not fire behind an open dialog.
    await user.keyboard("gq");
    expect(location()).toBe("/overview?fund=GEF1&day=2026-11-10");

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("does not move screens while typing in the day selector's neighbour fields", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    await screen.findByRole("heading", { name: "Morning overview" });
    const select = screen.getByLabelText("Fund");
    fireEvent.keyDown(select, { key: "g" });
    fireEvent.keyDown(select, { key: "q" });
    expect(location()).toBe("/overview?fund=GEF1&day=2026-11-10");
  });
});
