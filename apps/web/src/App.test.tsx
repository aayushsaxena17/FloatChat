import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.unstubAllGlobals());

it("renders the scaffold and reaches readiness", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true });
  vi.stubGlobal("fetch", fetch);
  render(<App />);
  expect(screen.getByRole("heading")).toHaveTextContent("Explore the ocean");
  expect(await screen.findByText("Local services ready")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith("/v1/health/ready", expect.any(Object));
});

it.each([false, "reject"])(
  "shows unavailable services for %s",
  async (result) => {
    vi.stubGlobal(
      "fetch",
      result === "reject"
        ? vi.fn().mockRejectedValue(new Error("offline"))
        : vi.fn().mockResolvedValue({ ok: result }),
    );
    render(<App />);
    expect(
      await screen.findByText("Local services unavailable"),
    ).toBeInTheDocument();
  },
);
