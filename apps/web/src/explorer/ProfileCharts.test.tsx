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
    const first = screen
      .getByRole("heading", { name: "Temperature versus pressure" })
      .closest("section") as HTMLElement;
    await userEvent.click(within(first).getByRole("button", { name: "Table" }));
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
