import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { CoverageResponse } from "../api/types";
import { CoveragePanel } from "./CoveragePanel";
import coverage from "../test/fixtures/coverage.json";

const response = coverage as unknown as CoverageResponse;

describe("CoveragePanel", () => {
  it("shows the range, region, counts, missingness, source and ingestion timestamps", async () => {
    render(<CoveragePanel coverage={response} />);
    expect(
      screen.getByRole("heading", { name: /Coverage/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", {
      name: "Coverage & ingestion details",
    });
    await userEvent.click(trigger);
    const details = within(
      screen.getByRole("dialog", { name: "Coverage & ingestion details" }),
    );
    expect(details.getByText("FloatChat ingestion")).toBeVisible();
    expect(details.getByText(/1 Jan 2025 to 1 Feb 2025/)).toBeInTheDocument();
    expect(screen.getByText(/Arabian Sea \(iho-v3/)).toBeInTheDocument();
    expect(
      screen.getByText(String(response.coverage.estimated_profiles)),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/covered, .* verified empty, .* missing of/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Source retrieved/)).toBeInTheDocument();
    expect(screen.getByText(/FloatChat ingestion/)).toBeInTheDocument();
    expect(
      screen.getByText(/9 Oct 2026 · \d\d:\d\d UTC to 9 Oct 2026/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        response.coverage.partial ? "partial coverage" : "coverage complete",
      ),
    ).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("labels partial coverage in text and lists the missing tiles", async () => {
    const partial: CoverageResponse = {
      ...response,
      coverage: {
        ...response.coverage,
        partial: true,
        slots_missing: 1,
        missing: [
          {
            slot: "s",
            month: "2025-01",
            tile: { west: 50, south: 0 },
            state: "missing",
            gaps: ["fetch_coverage"],
            profiles: 0,
            levels: 0,
            parts: 0,
          },
        ],
      },
    };
    render(<CoveragePanel coverage={partial} />);
    expect(screen.getByText("partial coverage")).toBeInTheDocument();
    expect(screen.getByText("Some source data is missing")).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "Coverage & ingestion details" }),
    );
    expect(
      screen.getByText(/2025-01: 50°E\/0°N \(fetch_coverage\)/),
    ).toBeVisible();
  });

  it("says when no completed run defines the timestamps", async () => {
    const bare: CoverageResponse = {
      ...response,
      environment: {
        ...response.environment,
        ingested_at: null,
        source_retrieved: null,
        latest_run: null,
      },
    };
    render(<CoveragePanel coverage={bare} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Coverage & ingestion details" }),
    );
    expect(
      screen.getByText(/unknown \(no completed run\)/),
    ).toBeInTheDocument();
  });
});
