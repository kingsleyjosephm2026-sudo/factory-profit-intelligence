import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../state", () => ({ useApp: () => ({ filters: {}, version: 0, config: null }) }));
vi.mock("../api", async (orig) => ({ ...(await orig<typeof import("../api")>()), get: vi.fn().mockResolvedValue({}) }));

import { DataTable, EmptyState, Kpi } from "./ui";

const card = { key: "defect", label: "Defect rate", value: 1.73, previous: 1.68, unit: "%", abs_diff: 0.05, pct_diff: 3.1, better: "lower" as const, definition_key: null };

describe("Kpi", () => {
  it("shows value, previous value, absolute and percentage difference", () => {
    render(<Kpi card={card} currency="INR" />);
    expect(screen.getByText("1.73%")).toBeInTheDocument();
    expect(screen.getByText(/\+0.05%/)).toBeInTheDocument();
    expect(screen.getByText(/\+3.1%/)).toBeInTheDocument();
    expect(screen.getByText("deterioration")).toBeInTheDocument(); // defect rate rising is bad
  });
  it("does not invent a percentage when the previous value is zero", () => {
    render(<Kpi card={{ ...card, previous: 0, pct_diff: null, abs_diff: 1.73 }} currency="INR" />);
    expect(screen.getByText(/% n\/a/)).toBeInTheDocument();
  });
  it("says so when there is no previous period", () => {
    render(<Kpi card={{ ...card, previous: null, abs_diff: null, pct_diff: null }} currency="INR" />);
    expect(screen.getByText("No previous-period data")).toBeInTheDocument();
  });
});

describe("DataTable", () => {
  const rows = [{ n: "b", v: 2 }, { n: "a", v: 3 }, { n: "c", v: 1 }];
  const cols = [{ key: "n", label: "Name" }, { key: "v", label: "Value", align: "right" as const }];
  it("sorts when a header is clicked and toggles direction", () => {
    render(<DataTable rows={rows} cols={cols} />);
    const order = () => within(screen.getAllByRole("row").slice(1)[0]).getAllByRole("cell")[0].textContent;
    fireEvent.click(screen.getByRole("button", { name: /Name/ }));
    expect(order()).toBe("c"); // descending first
    fireEvent.click(screen.getByRole("button", { name: /Name/ }));
    expect(order()).toBe("a");
  });
  it("paginates", () => {
    const many = Array.from({ length: 25 }, (_, i) => ({ n: `r${i}`, v: i }));
    render(<DataTable rows={many} cols={cols} pageSize={10} />);
    expect(screen.getAllByRole("row")).toHaveLength(11);
    fireEvent.click(screen.getByLabelText("Next page"));
    expect(screen.getByText(/Page 2 of 3/)).toBeInTheDocument();
  });
  it("renders an empty state instead of an empty table", () => {
    render(<DataTable rows={[]} cols={cols} />);
    expect(screen.getByText(/No data for the selected filters/)).toBeInTheDocument();
    render(<EmptyState message="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
