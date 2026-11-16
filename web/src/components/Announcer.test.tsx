import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnnouncerProvider, useAnnounce } from "./Announcer";

let announce: (message: string) => void = () => {};

function Grab() {
  announce = useAnnounce();
  return null;
}

describe("Announcer", () => {
  it("is one polite status region, in the page before anything is said", () => {
    render(
      <AnnouncerProvider>
        <Grab />
      </AnnouncerProvider>,
    );
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveAttribute("aria-atomic", "true");
    expect(region).toHaveTextContent("");
  });

  it("says each message, and the same words twice still change the region", () => {
    render(
      <AnnouncerProvider>
        <Grab />
      </AnnouncerProvider>,
    );
    const region = screen.getByTestId("announcer");
    act(() => announce("Approved C-1. Recorded in the audit log."));
    expect(region).toHaveTextContent("Approved C-1. Recorded in the audit log.");
    const first = region.textContent;
    act(() => announce("Approved C-1. Recorded in the audit log."));
    expect(region).toHaveTextContent("Approved C-1. Recorded in the audit log.");
    expect(region.textContent).not.toBe(first);
  });

  it("does nothing outside the provider", () => {
    render(<Grab />);
    expect(() => announce("Nobody hears this.")).not.toThrow();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
