import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Day, DayRun, Job } from "../../api/types";
import { mockApi } from "../../test/mockApi";
import { dayRecord, daysList, intakeFor, location, renderApp, signedInRoutes } from "../../test/render";

const DAY = "/api/funds/GEF1/days/2026-11-11";
const TODAY = "/api/funds/GEF1/days/2026-11-10";

function csv(name: string): File {
  return new File(["a,b\n1,2\n"], name, { type: "text/csv" });
}

function heldFile(filename: string, kind: string) {
  return {
    kind,
    filename,
    sha256: "cd".repeat(32),
    size_bytes: 3 * 1024,
    uploaded_by: "analyst1",
    uploaded_at: "2026-11-10T07:55:00+00:00",
  };
}

function run(overrides: Partial<DayRun>): DayRun {
  return {
    job_id: 1,
    status: "done",
    attempts: 1,
    max_attempts: 3,
    started_by: "analyst1",
    rerun: false,
    queued_at: "2026-11-10T08:00:00+00:00",
    started_at: "2026-11-10T08:00:01+00:00",
    finished_at: "2026-11-10T08:00:02+00:00",
    duration_seconds: 0.8,
    error: null,
    outcome: {
      open_cases: 6,
      new_cases: 4,
      carried_cases: 2,
      cleared_today: 1,
      breaks: 9,
      matches: 120,
      decisions_reapplied: 0,
      decisions_voided: 0,
      cases_withdrawn: 0,
    },
    skipped: null,
    ...overrides,
  };
}

function job(overrides: Partial<Job>): Job {
  return {
    id: 7,
    kind: "run_day",
    status: "running",
    attempts: 1,
    max_attempts: 3,
    error: null,
    result: null,
    created_at: "2026-11-10T08:00:00+00:00",
    started_at: "2026-11-10T08:00:01+00:00",
    finished_at: null,
    ...overrides,
  };
}

describe("Upload and run: whether the day can take files", () => {
  it("says in plain words that the previous day is not signed off, and offers its sign-off", async () => {
    mockApi({
      ...signedInRoutes(),
      [`GET ${DAY}`]: { status: 404, body: { detail: "No files have been uploaded for 2026-11-11." } },
      [`GET ${DAY}/intake`]: {
        body: intakeFor("GEF1", "2026-11-11", {
          open: false,
          blocked: { code: "PREVIOUS_NOT_SIGNED_OFF", message: "Sign off 2026-11-10 first.", day: "2026-11-10", day_status: "ready" },
          previous_business_day: "2026-11-10",
          previous_status: "ready",
          following_day: "2026-11-12",
        }),
      },
    });
    renderApp("/upload?fund=GEF1&day=2026-11-11");
    const notice = await screen.findByText("Tue 10 Nov 2026 is not signed off yet.");
    const box = notice.closest(".up-order") as HTMLElement;
    expect(box).toHaveTextContent(
      "Days are worked in order, so Wed 11 Nov 2026’s files can be loaded only after that day’s NAV is signed off. " +
        "It is ready for review, with its cases being decided.",
    );
    expect(within(box).getByRole("link", { name: "Open the sign-off for Tue 10 Nov 2026" })).toHaveAttribute(
      "href",
      "/signoff?fund=GEF1&day=2026-11-10",
    );
    expect(screen.queryByLabelText(/Choose the day/)).not.toBeInTheDocument();
    expect(screen.queryByText(/No files have been uploaded/)).not.toBeInTheDocument();
  });

  it("sends the person to load the previous day when it has no files at all", async () => {
    mockApi({
      ...signedInRoutes(),
      [`GET ${DAY}`]: { status: 404, body: { detail: "No files." } },
      [`GET ${DAY}/intake`]: {
        body: intakeFor("GEF1", "2026-11-11", {
          open: false,
          blocked: { code: "PREVIOUS_NOT_LOADED", message: "Sign off 2026-11-10 first.", day: "2026-11-10", day_status: null },
        }),
      },
    });
    const user = userEvent.setup();
    renderApp("/upload?fund=GEF1&day=2026-11-11");
    expect(await screen.findByText("Tue 10 Nov 2026 has no files yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Go to Tue 10 Nov 2026" }));
    await waitFor(() => expect(location()).toBe("/upload?fund=GEF1&day=2026-11-10"));
  });

  it("explains a day that is not a business day", async () => {
    mockApi({
      ...signedInRoutes(),
      [`GET ${DAY}`]: { status: 404, body: { detail: "No files." } },
      [`GET ${DAY}/intake`]: {
        body: intakeFor("GEF1", "2026-11-11", {
          open: false,
          blocked: { code: "NOT_BUSINESS_DAY", message: "x", day: "2026-11-11", day_status: null },
        }),
      },
    });
    renderApp("/upload?fund=GEF1&day=2026-11-11");
    expect(await screen.findByText("Wed 11 Nov 2026 is not a business day for GEF1.")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Choose the day/)).not.toBeInTheDocument();
  });
});

describe("Upload and run: files and checks", () => {
  function loaded(overrides: Partial<Day> = {}): Day {
    return dayRecord("GEF1", "2026-11-11", {
      status: "uploaded",
      nav: null,
      run_by: null,
      run_at: null,
      files: [heldFile("book_trades.csv", "trades"), heldFile("fund.csv", "fund")],
      validation: {
        errors: [
          { file: "fund.csv", row: 3, message: "as_of is 2026-11-10, not 2026-11-11." },
          { file: "book_trades.csv", row: 7, message: "settle_date is before trade_date." },
          { file: "securities.csv", row: null, message: "Required file is missing." },
        ],
        warnings: [{ file: "book_trades.csv", row: 2, message: "fees is blank; read as 0." }],
      },
      ...overrides,
    });
  }

  it("shows every expected file as held or missing, with what the checks found in it", async () => {
    mockApi({
      ...signedInRoutes(),
      "GET /api/funds/GEF1/days": {
        body: daysList("GEF1", [
          { as_of: "2026-11-11", status: "uploaded" },
          { as_of: "2026-11-10", status: "signed_off" },
        ]),
      },
      [`GET ${DAY}`]: { body: loaded() },
      [`GET ${DAY}/intake`]: { body: intakeFor("GEF1", "2026-11-11", { day_status: "uploaded" }) },
      [`GET ${DAY}/runs`]: { body: { fund: "GEF1", as_of: "2026-11-11", runs: [] } },
    });
    renderApp("/upload?fund=GEF1&day=2026-11-11");
    const table = await screen.findByRole("table", { name: /Files held for Wed 11 Nov 2026/ });
    const row = (name: string) => within(table).getByRole("row", { name: new RegExp(`^${name.replace(".", "\\.")}`) });
    expect(within(table).getAllByRole("row")).toHaveLength(9);
    expect(row("book_trades.csv")).toHaveTextContent("1 error, 1 warning");
    expect(row("book_trades.csv")).toHaveTextContent("3 KB");
    expect(row("fund.csv")).toHaveTextContent("1 error");
    expect(row("securities.csv")).toHaveTextContent("Missing, needed for the run");
    expect(row("prior_prices.csv")).toHaveTextContent("Not uploaded (optional)");

    // Errors by file, in the engine's order of files, then by row.
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("3 problems block the run");
    const where = within(alert)
      .getAllByRole("listitem")
      .map((li) => li.querySelector(".up-issue-where")?.textContent);
    expect(where).toEqual(["securities.csv", "book_trades.csv, row 7", "fund.csv, row 3"]);
    expect(screen.getByText("1 warning")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run the day/ })).not.toBeInTheDocument();
  });

  it("sends only the files ReconPilot reads and lists the rest", async () => {
    const api = mockApi({
      ...signedInRoutes(),
      "GET /api/funds/GEF1/days": {
        body: daysList("GEF1", [{ as_of: "2026-11-10", status: "signed_off" }], "2026-11-11"),
      },
      [`GET ${DAY}`]: { status: 404, body: { detail: "No files." } },
      [`GET ${DAY}/intake`]: { body: intakeFor("GEF1", "2026-11-11") },
      [`POST ${DAY}/files`]: { body: { status: "uploaded", errors: [], warnings: [] } },
    });
    const user = userEvent.setup({ applyAccept: false });
    renderApp("/upload?fund=GEF1&day=2026-11-11");
    expect(await screen.findByText(/No files have been uploaded for Wed 11 Nov 2026 yet/)).toBeInTheDocument();
    expect(screen.getByText(/Up to 5 MB a file/)).toBeInTheDocument();
    await user.upload(screen.getByLabelText(/Choose the day/), [csv("BOOK_TRADES.csv"), csv("notes.txt"), csv("fund.csv")]);
    const sent = api.calls(`POST ${DAY}/files`);
    expect(sent).toHaveLength(1);
    expect((sent[0]?.body as FormData).getAll("files").map((f) => (f as File).name)).toEqual([
      "BOOK_TRADES.csv",
      "fund.csv",
    ]);
    expect(screen.getByText(/Not sent: notes\.txt\. It is not a file ReconPilot reads for a day\./)).toBeInTheDocument();
  });
});

describe("Upload and run: the run", () => {
  it("follows a run through its steps and says when an attempt failed and will be tried again", async () => {
    mockApi({
      ...signedInRoutes(),
      "GET /api/funds/GEF1/days": { body: daysList("GEF1", [{ as_of: "2026-11-10", status: "running" }]) },
      [`GET ${TODAY}`]: { body: dayRecord("GEF1", "2026-11-10", { status: "running", job: job({}) }) },
      [`GET ${TODAY}/intake`]: {
        body: intakeFor("GEF1", "2026-11-10", {
          open: false,
          day_status: "running",
          blocked: { code: "RUNNING", message: "x", day: "2026-11-10", day_status: "running" },
        }),
      },
      [`GET ${TODAY}/runs`]: { body: { fund: "GEF1", as_of: "2026-11-10", runs: [run({ job_id: 7, status: "queued", outcome: null, finished_at: null, duration_seconds: null, error: "RuntimeError: disk on fire" })] } },
      "GET /api/jobs/7": { body: job({ status: "queued", error: "RuntimeError: disk on fire", finished_at: null }) },
    });
    renderApp("/upload?fund=GEF1&day=2026-11-10");
    const steps = await screen.findByRole("list", { name: "Run progress" });
    expect(within(steps).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Queued for the worker (now)",
      "Matching, triage, NAV and checks",
      "Cases ready",
    ]);
    expect(
      await screen.findByText(/Attempt 1 of 3 failed: RuntimeError: disk on fire It is tried again automatically\./),
    ).toBeInTheDocument();
    // No upload while the day runs.
    expect(screen.queryByLabelText(/Choose the day/)).not.toBeInTheDocument();
  });

  it("lists the day's runs, newest first, with what each found, and says which day opens next", async () => {
    mockApi({
      ...signedInRoutes(),
      [`GET ${TODAY}`]: {
        body: dayRecord("GEF1", "2026-11-10", { files: [heldFile("book_trades.csv", "trades")], summary: { open_cases: 5 } }),
      },
      [`GET ${TODAY}/intake`]: { body: intakeFor("GEF1", "2026-11-10", { day_status: "ready", following_day: "2026-11-11" }) },
      [`GET ${TODAY}/runs`]: {
        body: {
          fund: "GEF1",
          as_of: "2026-11-10",
          runs: [
            run({
              job_id: 2,
              duration_seconds: 2.43,
              started_by: "approver1",
              rerun: true,
              outcome: {
                open_cases: 5,
                new_cases: 3,
                carried_cases: 2,
                cleared_today: 0,
                breaks: 8,
                matches: 118,
                decisions_reapplied: 1,
                decisions_voided: 2,
                cases_withdrawn: 0,
              },
            }),
            run({ job_id: 1, status: "failed", outcome: null, attempts: 3, error: "RuntimeError: disk on fire" }),
          ],
        },
      },
    });
    renderApp("/upload?fund=GEF1&day=2026-11-10");
    const history = await screen.findByRole("table", { name: "Runs of Tue 10 Nov 2026, newest first" });
    const rows = within(history).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("approver1, re-run");
    expect(rows[0]).toHaveTextContent("Finished");
    expect(rows[0]).toHaveTextContent("5 open cases (3 new, 2 carried); 8 breaks found.");
    expect(rows[0]).toHaveTextContent("Re-run: 1 decision kept, 2 decisions voided.");
    expect(rows[0]).toHaveTextContent("2.4 s");
    expect(rows[1]).toHaveTextContent("Failed");
    expect(rows[1]).toHaveTextContent("RuntimeError: disk on fire");
    expect(screen.getByText("2 runs of Tue 10 Nov 2026")).toBeInTheDocument();

    const hint = screen.getByText(/opens for its files once/);
    expect(hint).toHaveTextContent("Wed 11 Nov 2026 opens for its files once Tue 10 Nov 2026 is signed off.");
    expect(within(hint).getByRole("link", { name: "signed off" })).toHaveAttribute("href", "/signoff?fund=GEF1&day=2026-11-10");
  });
});
