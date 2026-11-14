import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Day, Job, User } from "../../api/types";
import { mockApi } from "../../test/mockApi";
import { dayRecord, daysList, location, renderApp, signedInRoutes } from "../../test/render";

const viewer: User = { username: "viewer1", display_name: "Val Kerr", role: "viewer", is_admin: false };
const DAY = "/api/funds/INC2/days/2026-11-10";

function csv(name: string): File {
  return new File(["a,b\n1,2\n"], name, { type: "text/csv" });
}

function job(status: string): Job {
  return {
    id: 7,
    kind: "run_day",
    status,
    attempts: 1,
    max_attempts: 3,
    error: null,
    result: null,
    created_at: "2026-11-10T08:00:00+00:00",
    started_at: "2026-11-10T08:00:01+00:00",
    finished_at: status === "done" ? "2026-11-10T08:00:02+00:00" : null,
  };
}

function loadedDay(overrides: Partial<Day>): Day {
  return dayRecord("INC2", "2026-11-10", {
    status: "validated",
    nav: null,
    run_by: null,
    run_at: null,
    files: [
      {
        kind: "trades",
        filename: "book_trades.csv",
        sha256: "ab".repeat(32),
        size_bytes: 2048,
        uploaded_by: "analyst1",
        uploaded_at: "2026-11-10T07:55:00+00:00",
      },
    ],
    validation: { errors: [], warnings: [] },
    ...overrides,
  });
}

describe("UploadScreen", () => {
  it("opens the next business day from a signed-off one, uploads the files and shows what blocks the run", async () => {
    let uploaded = false;
    const api = mockApi({
      ...signedInRoutes(),
      [`GET ${DAY}`]: () =>
        uploaded
          ? {
              body: loadedDay({
                status: "uploaded",
                validation: {
                  errors: [{ file: "book_trades.csv", row: 4, message: "settle_date is before trade_date." }],
                  warnings: [{ file: "fund.csv", row: null, message: "management_fee_rate is blank; read as 0." }],
                },
              }),
            }
          : { status: 404, body: { detail: "No files have been uploaded for 2026-11-10." } },
      [`POST ${DAY}/files`]: () => {
        uploaded = true;
        return { body: { status: "uploaded", errors: [], warnings: [] } };
      },
      "GET /api/funds/INC2/days": {
        body: daysList("INC2", [{ as_of: "2026-11-09", status: "signed_off" }], "2026-11-10"),
      },
    });
    const user = userEvent.setup();
    renderApp("/upload?fund=INC2&day=2026-11-09");

    expect(await screen.findByText(/is signed off; its files are locked/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load Tue 10 Nov 2026" }));
    await waitFor(() => expect(location()).toContain("day=2026-11-10"));
    expect(await screen.findByText(/No files have been uploaded for Tue 10 Nov 2026 yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run/ })).not.toBeInTheDocument();

    await user.upload(screen.getByLabelText(/Choose the day/), [csv("book_trades.csv"), csv("fund.csv")]);

    const sent = api.calls(`POST ${DAY}/files`);
    expect(sent).toHaveLength(1);
    const form = sent[0]?.body as FormData;
    expect(form.getAll("files").map((f) => (f as File).name)).toEqual(["book_trades.csv", "fund.csv"]);

    expect(await screen.findByText(/1 problem blocks the run/)).toBeInTheDocument();
    expect(screen.getByText("book_trades.csv, row 4")).toBeInTheDocument();
    expect(screen.getByText("settle_date is before trade_date.")).toBeInTheDocument();
    expect(screen.getByText("1 warning")).toBeInTheDocument();
    expect(screen.getByText("The run opens once the files are valid.")).toBeInTheDocument();
  });

  it("runs a validated day, follows the job and offers the cases when it is ready", async () => {
    let phase: "validated" | "running" | "ready" = "validated";
    const api = mockApi({
      ...signedInRoutes(),
      "GET /api/funds/INC2/days": {
        body: daysList("INC2", [
          { as_of: "2026-11-10", status: "validated" },
          { as_of: "2026-11-09", status: "signed_off" },
        ]),
      },
      [`GET ${DAY}`]: () => ({
        body:
          phase === "ready"
            ? loadedDay({ status: "ready", run_by: "analyst1", run_at: "2026-11-10T08:00:02+00:00", summary: { open_cases: 5 } })
            : loadedDay({ status: phase, job: phase === "running" ? job("running") : null }),
      }),
      [`GET ${DAY}/release`]: { body: { ready: false, reasons: [], checks: [], signable_by_me: false, blocking_for_me: [] } },
      [`POST ${DAY}/run`]: () => {
        phase = "running";
        return { status: 202, body: { job_id: 7 } };
      },
      "GET /api/jobs/7": () => {
        phase = "ready";
        return { body: job("done") };
      },
    });
    const user = userEvent.setup();
    renderApp("/upload?fund=INC2&day=2026-11-10");

    expect(await screen.findByText("The files are valid.")).toBeInTheDocument();
    expect(screen.getByText("book_trades.csv")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run the day" }));

    expect(await screen.findByText(/Run by analyst1, .*: 5 open cases\./)).toBeInTheDocument();
    expect(api.calls(`POST ${DAY}/run`)).toHaveLength(1);
    expect(api.calls("GET /api/jobs/7").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Work the cases" })).toHaveAttribute("href", "/cases?fund=INC2&day=2026-11-10");
    expect(screen.getByRole("button", { name: "Run again" })).toBeInTheDocument();
    // Once the day has run, the file list folds away behind one line.
    const held = screen.getByText("Show the 1 file held for Tue 10 Nov 2026").closest("details");
    expect(held).not.toHaveAttribute("open");
    expect(held).toContainElement(screen.getByRole("table", { name: /Files held for Tue 10 Nov 2026/, hidden: true }));
  });

  it("runs the day from the command palette, for those who may run it", async () => {
    const api = mockApi({
      ...signedInRoutes(),
      "GET /api/funds/INC2/days": {
        body: daysList("INC2", [
          { as_of: "2026-11-10", status: "validated" },
          { as_of: "2026-11-09", status: "signed_off" },
        ]),
      },
      [`GET ${DAY}`]: { body: loadedDay({}) },
      [`GET ${DAY}/release`]: { body: { ready: false, reasons: [], checks: [], signable_by_me: false, blocking_for_me: [] } },
      [`POST ${DAY}/run`]: { status: 202, body: { job_id: 7 } },
      "GET /api/jobs/7": { body: job("running") },
    });
    const user = userEvent.setup();
    renderApp("/upload?fund=INC2&day=2026-11-10");
    await screen.findByText("The files are valid.");
    await user.keyboard("{Control>}k{/Control}");
    await screen.findByRole("dialog", { name: "Command palette" });
    await user.keyboard("run tue{Enter}");
    await waitFor(() => expect(api.calls(`POST ${DAY}/run`)).toHaveLength(1));
  });

  it("shows the server's refusal in its own words", async () => {
    mockApi({
      ...signedInRoutes(),
      [`GET ${DAY}`]: { body: loadedDay({}) },
      "GET /api/funds/INC2/days": {
        body: daysList("INC2", [
          { as_of: "2026-11-10", status: "validated" },
          { as_of: "2026-11-09", status: "signed_off" },
        ]),
      },
      [`POST ${DAY}/run`]: { status: 409, body: { detail: "2026-11-10 is already running." } },
    });
    const user = userEvent.setup();
    renderApp("/upload?fund=INC2&day=2026-11-10");
    await user.click(await screen.findByRole("button", { name: "Run the day" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("2026-11-10 is already running.");
  });

  it("lets a viewer see the files but not upload or run", async () => {
    mockApi({
      ...signedInRoutes(viewer),
      [`GET ${DAY}`]: { body: loadedDay({}) },
      "GET /api/funds/INC2/days": {
        body: daysList("INC2", [
          { as_of: "2026-11-10", status: "validated" },
          { as_of: "2026-11-09", status: "signed_off" },
        ]),
      },
    });
    renderApp("/upload?fund=INC2&day=2026-11-10");
    expect(await screen.findByText("book_trades.csv")).toBeInTheDocument();
    expect(screen.getByText(/Viewers can follow the day but cannot upload files or run it/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Choose the day/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run/ })).not.toBeInTheDocument();
  });

  it("is reached with g u", async () => {
    mockApi({ ...signedInRoutes(), "GET /api/funds/GEF1/days/2026-11-10/overview": { status: 500, body: { detail: "x" } } });
    const user = userEvent.setup();
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    await screen.findByRole("link", { name: /Upload/ });
    await user.keyboard("gu");
    await waitFor(() => expect(location()).toBe("/upload?fund=GEF1&day=2026-11-10"));
  });
});
