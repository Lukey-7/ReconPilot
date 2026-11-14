/**
 * A semantic, sortable table built on TanStack Table, shared by every screen that lists
 * cases or entries.
 *
 * - A real <table> with a <caption> (visually hidden if `captionHidden`).
 * - Sortable headers are buttons; the header cell carries `aria-sort`.
 * - Columns with `meta: { numeric: true }` are right-aligned with tabular figures.
 * - With `onActivate`, a row opens on click or on Enter when focused; `selectedId` marks
 *   the open row with `aria-selected`.
 * - Every body row carries `data-row-id`, and `onOrderChange` reports the row ids in the
 *   order shown (after sorting), so a screen can move through them from the keyboard.
 */
import {
  type ColumnDef,
  type RowData,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { Icon } from "./Icon";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    /** Right-align, tabular figures. */
    numeric?: boolean;
    /** Extra class for the column's cells. */
    className?: string;
  }
}

export interface DataTableProps<T> {
  data: T[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<T, any>[];
  caption: ReactNode;
  captionHidden?: boolean;
  getRowId: (row: T) => string;
  initialSorting?: SortingState;
  selectedId?: string | null;
  onActivate?: (row: T) => void;
  /** Called with the row ids in the order shown, whenever that order changes. */
  onOrderChange?: (ids: string[]) => void;
  empty?: ReactNode;
  className?: string;
}

export function DataTable<T>({
  data,
  columns,
  caption,
  captionHidden = false,
  getRowId,
  initialSorting = [],
  selectedId = null,
  onActivate,
  onOrderChange,
  empty = "Nothing to show.",
  className = "",
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId: (row) => getRowId(row),
  });

  const rows = table.getRowModel().rows;
  const order = JSON.stringify(rows.map((row) => row.id));
  const onOrderChangeRef = useRef(onOrderChange);
  useEffect(() => {
    onOrderChangeRef.current = onOrderChange;
  });
  useEffect(() => {
    onOrderChangeRef.current?.(JSON.parse(order) as string[]);
  }, [order]);

  return (
    <div className="table-wrap">
      <table className={`data-table ${className}`.trim()}>
        <caption className={captionHidden ? "sr-only" : undefined}>{caption}</caption>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => {
                const meta = header.column.columnDef.meta;
                const sorted = header.column.getIsSorted();
                const ariaSort = sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined;
                const label = header.isPlaceholder
                  ? null
                  : flexRender(header.column.columnDef.header, header.getContext());
                return (
                  <th
                    key={header.id}
                    scope="col"
                    className={[meta?.numeric ? "num" : "", meta?.className ?? ""].join(" ").trim() || undefined}
                    aria-sort={ariaSort}
                  >
                    {header.column.getCanSort() ? (
                      <button type="button" className="sort-btn" onClick={header.column.getToggleSortingHandler()}>
                        {label}
                        <Icon name="sort" className={`sort-icon ${sorted ? `sorted-${sorted}` : ""}`} />
                      </button>
                    ) : (
                      label
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="empty-cell">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const selected = selectedId != null && row.id === selectedId;
              const activate = onActivate ? () => onActivate(row.original) : undefined;
              return (
                <tr
                  key={row.id}
                  data-row-id={row.id}
                  aria-selected={onActivate ? selected : undefined}
                  className={[onActivate ? "activatable" : "", selected ? "selected" : ""].join(" ").trim() || undefined}
                  tabIndex={onActivate ? 0 : undefined}
                  onClick={activate}
                  onKeyDown={
                    activate
                      ? (event) => {
                          if (event.key === "Enter" && event.target === event.currentTarget) {
                            event.preventDefault();
                            activate();
                          }
                        }
                      : undefined
                  }
                >
                  {row.getVisibleCells().map((cell) => {
                    const meta = cell.column.columnDef.meta;
                    return (
                      <td
                        key={cell.id}
                        className={[meta?.numeric ? "num" : "", meta?.className ?? ""].join(" ").trim() || undefined}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    );
                  })}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
