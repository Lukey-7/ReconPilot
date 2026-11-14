import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createColumnHelper } from "@tanstack/react-table";
import { describe, expect, it, vi } from "vitest";

import { DataTable } from "./DataTable";
import { CauseLabel, CheckLabel, ReleaseBadge, StatusLabel } from "./Labels";

interface Row {
  id: string;
  cause: string;
  impact: number;
}

const helper = createColumnHelper<Row>();
const columns = [
  helper.accessor("id", { header: "Case" }),
  helper.accessor("cause", { header: "Cause", cell: (c) => <CauseLabel cause={c.getValue()} />, enableSorting: false }),
  helper.accessor("impact", { header: "Impact", meta: { numeric: true } }),
];
const rows: Row[] = [
  { id: "C1", cause: "TIMING", impact: 10 },
  { id: "C2", cause: "DIVIDEND", impact: -30 },
  { id: "C3", cause: "UNKNOWN", impact: 20 },
];

function bodyIds() {
  return within(screen.getAllByRole("rowgroup")[1] as HTMLElement)
    .getAllByRole("row")
    .map((r) => within(r).getAllByRole("cell")[0]?.textContent);
}

describe("DataTable", () => {
  it("renders a captioned table with vocabulary words and right-aligned numbers", () => {
    render(<DataTable data={rows} columns={columns} caption="Open cases" getRowId={(r) => r.id} />);
    expect(screen.getByRole("table", { name: "Open cases" })).toBeInTheDocument();
    expect(screen.getByText("Late settlement")).toBeInTheDocument();
    expect(screen.getByText("Unexplained")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Impact" })).toHaveClass("num");
    expect(screen.getAllByRole("cell", { name: "-30" })[0]).toHaveClass("num");
  });

  it("sorts by a header button and reports it with aria-sort", async () => {
    render(<DataTable data={rows} columns={columns} caption="Open cases" getRowId={(r) => r.id} />);
    const user = userEvent.setup();
    const header = screen.getByRole("columnheader", { name: "Impact" });
    // Numbers sort largest first on the first click, as an impact column should.
    await user.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "descending");
    expect(bodyIds()).toEqual(["C3", "C1", "C2"]);
    await user.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "ascending");
    expect(bodyIds()).toEqual(["C2", "C1", "C3"]);
    expect(within(screen.getByRole("columnheader", { name: "Cause" })).queryByRole("button")).toBeNull();
  });

  it("activates a row by click or Enter and marks the selected one", async () => {
    const onActivate = vi.fn();
    render(
      <DataTable data={rows} columns={columns} caption="Open cases" getRowId={(r) => r.id} selectedId="C3" onActivate={onActivate} />,
    );
    const user = userEvent.setup();
    const row = screen.getByRole("row", { name: /C1/ });
    await user.click(row);
    expect(onActivate).toHaveBeenLastCalledWith(rows[0]);
    row.focus();
    await user.keyboard("{Enter}");
    expect(onActivate).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("row", { name: /C3/ })).toHaveAttribute("aria-selected", "true");
  });

  it("reports the rows in the order shown, and again after sorting", async () => {
    const onOrderChange = vi.fn();
    render(<DataTable data={rows} columns={columns} caption="Open cases" getRowId={(r) => r.id} onOrderChange={onOrderChange} />);
    expect(onOrderChange).toHaveBeenLastCalledWith(["C1", "C2", "C3"]);
    expect(screen.getByRole("row", { name: /C2/ })).toHaveAttribute("data-row-id", "C2");
    const header = screen.getByRole("columnheader", { name: "Impact" });
    await userEvent.setup().click(within(header).getByRole("button"));
    expect(onOrderChange).toHaveBeenLastCalledWith(["C3", "C1", "C2"]);
  });

  it("says when there is nothing to show", () => {
    render(<DataTable data={[]} columns={columns} caption="Open cases" getRowId={(r) => r.id} empty="No open cases." />);
    expect(screen.getByText("No open cases.")).toBeInTheDocument();
  });
});

describe("labels", () => {
  it("pair every status with a word, never colour alone", () => {
    render(
      <>
        <StatusLabel status="PENDING" />
        <StatusLabel status="REJECTED" />
        <CheckLabel status="FAIL" />
        <ReleaseBadge state="blocked" />
      </>,
    );
    expect(screen.getByText("Pending")).toHaveAttribute("data-status", "PENDING");
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Fail")).toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
  });
});
