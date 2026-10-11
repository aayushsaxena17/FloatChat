import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReadinessStatus } from "./ReadinessStatus";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("ReadinessStatus", () => {
  it("recovers after a startup failure and detects a later outage", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockRejectedValueOnce(new Error("startup"))
        .mockResolvedValueOnce(new Response("{}", { status: 200 }))
        .mockResolvedValueOnce(new Response("{}", { status: 503 })),
    );
    render(<ReadinessStatus />);
    await act(async () => {});
    expect(screen.getByText("Local services unavailable")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(screen.getByText("Local services ready")).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(screen.getByText("Local services unavailable")).toBeInTheDocument();
  });

  it("ignores an aborted Strict Mode request while the active check completes", async () => {
    vi.useFakeTimers();
    let complete: ((response: Response) => void) | undefined;
    const fetch = vi.fn(
      (_url: string, options: RequestInit) =>
        new Promise<Response>((resolve, reject) => {
          complete = resolve;
          options.signal?.addEventListener(
            "abort",
            () => reject(new Error("aborted")),
            { once: true },
          );
        }),
    );
    vi.stubGlobal("fetch", fetch);
    render(
      <StrictMode>
        <ReadinessStatus />
      </StrictMode>,
    );
    await act(async () => {});
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Checking local services…")).toBeInTheDocument();
    await act(async () => {
      complete?.(new Response("{}", { status: 200 }));
    });
    expect(screen.getByText("Local services ready")).toBeInTheDocument();
  });
});
