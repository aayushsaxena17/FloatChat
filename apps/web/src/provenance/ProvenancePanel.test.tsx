import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CollectionResponse, QueryResponse } from "../api/types";
import { ProvenancePanel } from "./ProvenancePanel";
import query from "../test/fixtures/query-line.json";
import profiles from "../test/fixtures/profiles.json";

const queryResponse = query as unknown as QueryResponse;
const listing = profiles as unknown as CollectionResponse;

describe("ProvenancePanel", () => {
  it("renders the section 17 fields of a query result", () => {
    render(<ProvenancePanel provenance={queryResponse.provenance} open />);
    const text = screen.getByTestId("provenance").textContent ?? "";
    expect(text).toContain("argovis (argovis-core-v1)");
    expect(text).toContain("reference time 2025-04-01 00:00 UTC");
    expect(text).toContain("Arabian Sea (iho-v3");
    expect(text).toContain("slots covered");
    expect(text).toContain("qc-policy-v1/science_ready");
    expect(text).toContain(queryResponse.provenance.result_sha256);
    expect(text).toContain(queryResponse.provenance.plan_sha256 as string);
    expect(text).toContain(queryResponse.provenance.application_commit);
    expect(text).toContain("postgresql");
    expect(text).toContain("10.17882/42182");
    expect(
      screen.getByRole("button", { name: "Copy JSON" }),
    ).toBeInTheDocument();
  });

  it("explains what a read has no plan or coverage for", () => {
    render(<ProvenancePanel provenance={listing.provenance} open />);
    const text = screen.getByTestId("provenance").textContent ?? "";
    expect(text).toContain("not resolved for a read");
    expect(text).toContain("Plan SHA-256none (read)");
    expect(text).toContain("runs ");
    expect(text).toContain("Ingested2026-10-09");
  });
});
