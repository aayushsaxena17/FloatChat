import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, stubApi } from "../test/client";
import parameters from "../test/fixtures/parameters.json";
import coverage from "../test/fixtures/coverage.json";
import profiles from "../test/fixtures/profiles.json";
import profile from "../test/fixtures/profile.json";
import float from "../test/fixtures/float.json";

vi.mock("../charts/Plot", () => ({
  Plot: ({ label }: { label: string }) => <div role="img" aria-label={label} />,
}));
const { ProfilesView } = await import("./ProfilesView");
afterEach(() => vi.unstubAllGlobals());

describe("ProfilesView", () => {
  it("replaces the multi-profile query with details and loads only the selected observation's charts", async () => {
    const api = stubApi({
      "/v1/catalog/parameters": parameters,
      "/v1/catalog/coverage": coverage,
      "/v1/profiles/": profile,
      "/v1/profiles": { ...profiles, next_cursor: null },
      "/v1/floats/": float,
    });
    renderWithProviders(
      <ProfilesView />,
      "/explore/profiles?region=Arabian+Sea&start=2025-01-01&end=2025-02-01&qc=science_ready",
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Inspect newest profile" }),
    );
    const details = await screen.findByRole("region", {
      name: "Profile details",
    });
    expect(
      await within(details).findByText(
        `Float ${profile.profile.platform_number}`,
      ),
    ).toBeInTheDocument();
    expect(within(details).getByText("Pressure range")).toBeInTheDocument();
    expect(
      screen.getAllByRole("heading", { name: "Temperature-salinity diagram" }),
    ).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Reset view" })).toHaveLength(
      3,
    );
    expect(api.calls.some((call) => call.startsWith("POST"))).toBe(false);
  });
});
