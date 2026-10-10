import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import type { ReactNode } from "react";

export function renderWithProviders(ui: ReactNode, path = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

type Fixture = Record<string, unknown>;

/** A fetch stub answering the API by path from recorded fixtures. */
export function stubApi(
  fixtures: Record<string, Fixture>,
  failures: Record<string, number> = {},
) {
  const calls: string[] = [];
  const fetch = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      calls.push(`${init?.method ?? "GET"} ${url}`);
      const path = url.replace(/^https?:\/\/[^/]+/, "");
      const key = Object.keys(fixtures).find((candidate) =>
        path.startsWith(candidate),
      );
      const failing = Object.keys(failures).find((candidate) =>
        path.startsWith(candidate),
      );
      if (failing) {
        return new Response(
          JSON.stringify({
            error: {
              code: "coverage_missing",
              message: "No committed coverage.",
              details: [],
              correlation_id: "trace-x",
            },
          }),
          {
            status: failures[failing],
            headers: {
              "Content-Type": "application/json",
              "X-Correlation-ID": "trace-x",
            },
          },
        );
      }
      if (!key)
        return new Response("{}", {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      return new Response(JSON.stringify(fixtures[key]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    },
  );
  vi.stubGlobal("fetch", fetch);
  return { fetch, calls };
}

import { vi } from "vitest";
