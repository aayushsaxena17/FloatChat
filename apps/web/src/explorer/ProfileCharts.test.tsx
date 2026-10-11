import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ProfileResponse } from "../api/types";
import fixture from "../test/fixtures/profile.json";

vi.mock("../charts/Plot", () => ({
  Plot: ({ label }: { label: string }) => (
    <div role="img" aria-label={label} data-testid="plot" />
  ),
}));

const { ProfileCharts } = await import("./ProfileCharts");
const profile = fixture as unknown as ProfileResponse;

describe("ProfileCharts", () => {
  it("replaces empty plots and their controls with a reason, then restores charts for another profile", () => {
    const missingSalinity = structuredClone(profile);
    const names = missingSalinity.levels.columns.map((column) => column.name);
    for (const row of missingSalinity.levels.rows) {
      row[names.indexOf("salinity")] = null;
      row[names.indexOf("salinity_qc")] = "4";
    }
    const { rerender } = render(<ProfileCharts profile={profile} />);
    expect(screen.getAllByTestId("plot")).toHaveLength(3);
    rerender(<ProfileCharts profile={missingSalinity} />);
    expect(screen.getAllByTestId("plot")).toHaveLength(1);
    expect(screen.getAllByText("No readings")).toHaveLength(2);
    expect(
      screen.getByText("Salinity readings are marked as bad quality."),
    ).toBeVisible();
    expect(
      screen.getByText("No usable salinity readings to pair with temperature."),
    ).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Reset view" })).toHaveLength(
      1,
    );
    expect(screen.getAllByRole("tab", { name: "Table" })).toHaveLength(1);
    expect(screen.queryByText(/0 plotted values/)).not.toBeInTheDocument();
    rerender(<ProfileCharts profile={profile} />);
    expect(screen.getAllByTestId("plot")).toHaveLength(3);
    expect(screen.queryByText("No readings")).not.toBeInTheDocument();
  });

  it("renders three charts with table views, the QC summary and provenance", async () => {
    render(<ProfileCharts profile={profile} />);
    expect(
      screen.getByRole("heading", { name: "Temperature versus pressure" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Practical salinity versus pressure",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Temperature-salinity diagram" }),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("plot")).toHaveLength(3);
    await userEvent.click(screen.getByText("How these charts are built"));
    expect(screen.getByText("Recorded at")).toBeVisible();
    expect(screen.getByText("Quality policy")).toBeVisible();
    expect(screen.getByText(/paired readings shown/)).toBeVisible();
    expect(screen.queryByText("Calculation details")).not.toBeInTheDocument();
    const first = screen
      .getByRole("heading", { name: "Temperature versus pressure" })
      .closest("section") as HTMLElement;
    await userEvent.click(within(first).getByRole("tab", { name: "Table" }));
    expect(
      within(first).getByRole("columnheader", { name: "Pressure (dbar)" }),
    ).toBeInTheDocument();
    expect(
      within(first).getByRole("columnheader", { name: "Temperature (°C)" }),
    ).toBeInTheDocument();
    expect(within(first).getAllByRole("row").length).toBeGreaterThan(2);
    expect(screen.getByText(/QC policy science_ready/)).toBeInTheDocument();
    expect(screen.getByTestId("provenance")).toBeInTheDocument();
  });
});
