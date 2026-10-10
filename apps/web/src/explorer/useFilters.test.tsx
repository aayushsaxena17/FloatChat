import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, it } from "vitest";
import { useFilters } from "./useFilters";

function setup(path: string) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
  );
  return renderHook(() => ({ ...useFilters(), search: useLocation().search }), {
    wrapper,
  });
}

describe("useFilters", () => {
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
});
