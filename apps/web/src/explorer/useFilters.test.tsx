import { act, render, renderHook, screen } from "@testing-library/react";
import { Suspense, useLayoutEffect, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import { describe, expect, it } from "vitest";
import { useFilters } from "./useFilters";

function setup(path: string) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
  );
  return renderHook(
    () => ({
      ...useFilters(),
      search: useLocation().search,
      navigate: useNavigate(),
    }),
    {
      wrapper,
    },
  );
}

describe("useFilters", () => {
  it("preserves edits when a pending navigation suspends and the old screen re-renders", async () => {
    let controls!: {
      update: ReturnType<typeof useFilters>["update"];
      refresh: () => void;
    };
    let suspended = false;
    let pause = true;
    const waiting = new Promise<void>(() => {});
    function Screen() {
      const { filters, update } = useFilters();
      const location = useLocation();
      const [, refresh] = useState(0);
      useLayoutEffect(() => {
        controls = { update, refresh: () => refresh((value) => value + 1) };
      });
      if (pause && filters.region === "Arabian Sea") {
        suspended = true;
        throw waiting;
      }
      return <output data-testid="url">{location.search}</output>;
    }
    render(
      <MemoryRouter initialEntries={["/dashboard?region=Indian+Ocean"]}>
        <Suspense fallback="Loading">
          <Screen />
        </Suspense>
      </MemoryRouter>,
    );
    await act(async () =>
      controls.update({ region: "Arabian Sea", depthMin: 0 }),
    );
    expect(suspended).toBe(true);
    // An urgent update (for example a query result) renders the still-visible old URL.
    await act(async () => {
      flushSync(() => controls.refresh());
      pause = false;
      controls.update({ depthMax: 100 });
    });
    const params = new URLSearchParams(
      screen.getByTestId("url").textContent ?? "",
    );
    expect(params.get("region")).toBe("Arabian Sea");
    expect(params.get("depth_min")).toBe("0");
    expect(params.get("depth_max")).toBe("100");
  });

  it("keeps every change when several land before a re-render", () => {
    const { result } = setup("/dashboard?region=Arabian+Sea");
    // The CI failure: the controls fire one after another inside one tick.
    act(() => {
      result.current.update({ start: "2025-01-01" });
      result.current.update({ end: "2025-02-01" });
      result.current.update({ depthMin: 0 });
      result.current.update({ depthMax: 100 });
    });
    const params = new URLSearchParams(result.current.search);
    expect(params.get("region")).toBe("Arabian Sea");
    expect(params.get("start")).toBe("2025-01-01");
    expect(params.get("end")).toBe("2025-02-01");
    expect(params.get("depth_min")).toBe("0");
    expect(params.get("depth_max")).toBe("100");
    expect(result.current.filters).toMatchObject({
      start: "2025-01-01",
      end: "2025-02-01",
      depthMin: 0,
      depthMax: 100,
    });
  });

  it("follows the URL after each update across renders", () => {
    const { result } = setup("/dashboard");
    act(() => result.current.update({ region: "Bay of Bengal" }));
    act(() => result.current.update({ start: "2025-03-01" }));
    expect(result.current.filters.region).toBe("Bay of Bengal");
    expect(result.current.filters.start).toBe("2025-03-01");
  });

  it("uses link and history destinations after a no-op filter update", () => {
    const { result } = setup("/dashboard?region=Arabian+Sea");
    act(() => result.current.update({ depthMin: 0 }));
    act(() => result.current.update({ depthMin: 0 }));
    act(() => result.current.navigate("/dashboard?region=Bay+of+Bengal"));
    act(() => result.current.update({ depthMax: 100 }));
    expect(result.current.filters).toMatchObject({
      region: "Bay of Bengal",
      depthMin: null,
      depthMax: 100,
    });
    act(() => result.current.navigate(-1));
    expect(result.current.filters).toMatchObject({
      region: "Arabian Sea",
      depthMin: 0,
      depthMax: null,
    });
    act(() => result.current.update({ depthMax: 200 }));
    expect(result.current.filters).toMatchObject({
      region: "Arabian Sea",
      depthMin: 0,
      depthMax: 200,
    });
    act(() => result.current.navigate(1));
    expect(result.current.filters).toMatchObject({
      region: "Bay of Bengal",
      depthMin: null,
      depthMax: 100,
    });
  });
});
