import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubApi } from "../test/client";

vi.mock("../charts/Plot", () => ({ Plot: () => <div data-testid="plot" /> }));
vi.mock("../explorer/MapView", () => ({
  MapView: () => <p role="status">0 profiles plotted</p>,
}));

const { App } = await import("./App");

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("App shell", () => {
  it("redirects the root to the dashboard, reports readiness and cites the data", async () => {
    stubApi({ "/v1/health/ready": { status: "ok" } });
    render(<App />);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Dashboard" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Local services ready")).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Primary" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Skip to content" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toHaveTextContent(
      "doi:10.17882/42182",
    );
    expect(screen.getByRole("contentinfo")).toHaveTextContent("Natural Earth");
  });

  it("names the stage that delivers a stubbed route", async () => {
    stubApi({ "/v1/health/ready": { status: "ok" } });
    window.history.replaceState(null, "", "/jobs/123");
    render(<App />);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Jobs" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/arrives with Stage 5/)).toBeInTheDocument();
  });

  it("reports unavailable services", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(<App />);
    expect(
      await screen.findByText("Local services unavailable"),
    ).toBeInTheDocument();
  });
});
