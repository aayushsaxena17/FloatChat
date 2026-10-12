import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import queryLine from "../test/fixtures/query-line.json";
import { renderWithProviders } from "../test/client";

vi.mock("../charts/Plot", () => ({
  Plot: ({ label }: { label: string }) => <div role="img" aria-label={label} />,
}));

const { ChatPage } = await import("./ChatPage");

const PLAN = {
  dataset: "core",
  plan_schema: "stage2-plan-v1",
  time_range: { start: "2025-01-01T00:00:00Z", end: "2025-04-01T00:00:00Z" },
  geography: { kind: "named_region", value: "Arabian Sea" },
  depth_dbar: { min: 0, max: 100 },
  variables: ["temperature"],
  qc_policy: "science_ready",
  operation: {
    kind: "aggregate",
    group_by: ["month"],
    metrics: ["mean"],
    unit: "profile",
  },
  presentation: { kind: "line_chart" },
};

const INTERPRETATION = {
  classification: "query",
  kind: "plan",
  provider: "offline",
  model: "offline-rules-v1",
  prompt_version: "planner-v1",
  narrator_version: "narrator-v1",
  embedding_model: "hash-embed-v1",
  retrieval_mode: "rag_examples",
  retrieved: [
    {
      id: "region_alias:Arabian Sea",
      doc_type: "region_alias",
      title: "aliases",
      score: 0.42,
    },
  ],
  examples: [],
  reference_time: "2025-04-01T00:00:00Z",
  plan: PLAN,
  plan_sha256: "a".repeat(64),
  timings: { plan: 1.2 },
  tokens: { input: 0, output: 0 },
  transformation: "monthly means",
  narrative_source: "template",
  narrative_rejected: false,
};

function message(
  kind: string,
  text: string,
  payload: Record<string, unknown>,
  seq = 2,
) {
  return {
    id: `m${seq}`,
    conversation_id: "c1",
    seq,
    role: "assistant",
    kind,
    text,
    payload,
    correlation_id: "t-1",
    created_at: "2026-10-12T00:00:00Z",
  };
}

function sse(events: Array<[string, unknown]>): string {
  return events
    .map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
}

function stubChat(stream: string | null, status = 200, stored: unknown[] = []) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.includes("/v1/chat/messages")) {
        if (stream === null)
          return new Response(
            JSON.stringify({
              error: {
                code: "llm_unavailable",
                message: "unavailable",
                details: [],
                correlation_id: "t-9",
              },
            }),
            { status, headers: { "Content-Type": "application/json" } },
          );
        return new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        });
      }
      if (url.includes("/v1/chat/conversations/c1"))
        return new Response(
          JSON.stringify({
            conversation: {
              id: "c1",
              title: "t",
              message_count: 2,
              created_at: "",
              updated_at: "",
            },
            messages: stored,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      if (url.includes("/v1/chat/conversations"))
        return new Response(JSON.stringify({ conversations: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      return new Response("{}", {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

// The first scenario renders charts, a table and the provenance panel through a streamed
// response; a shared GitHub runner is slower than this host.
vi.setConfig({ testTimeout: 30000 });

describe("ChatPage", () => {
  it("streams an answer and shows the interpretation panel with the result", async () => {
    const user = {
      id: "m1",
      conversation_id: "c1",
      seq: 1,
      role: "user",
      kind: "user",
      text: "q",
      payload: {},
      correlation_id: null,
      created_at: "",
    };
    const result = { ...queryLine, plan: PLAN };
    const answer = message(
      "answer",
      "mean of temperature by month in the Arabian Sea: 3 rows.",
      { interpretation: INTERPRETATION, plan: PLAN, result },
    );
    const stream = sse([
      ["conversation", { conversation_id: "c1", user_message: user }],
      ["status", { step: "classify" }],
      ["status", { step: "plan" }],
      ["interpretation", INTERPRETATION],
      ["result", result],
      ["token", { text: "mean of temperature by month " }],
      ["token", { text: "in the Arabian Sea: 3 rows." }],
      ["message", answer],
    ]);
    // After the stream the page refetches the conversation; the server returns the stored rows.
    const calls = stubChat(stream, 200, [user, answer]);
    renderWithProviders(<ChatPage />, "/chat");
    const input = await screen.findByLabelText("Your question");
    await userEvent.click(input);
    await userEvent.paste(
      "monthly mean temperature in the Arabian Sea in Q1 2025",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    const thread = screen.getByTestId("chat-thread");
    await waitFor(() =>
      expect(thread).toHaveTextContent(
        "mean of temperature by month in the Arabian Sea: 3 rows.",
      ),
    );
    expect(
      calls.some(
        (call) => call.startsWith("POST") && call.includes("/v1/chat/messages"),
      ),
    ).toBe(true);
    const toggle = await screen.findByRole("button", {
      name: /How FloatChat interpreted your request/,
    });
    expect(toggle).toHaveTextContent(
      "offline/offline-rules-v1 (rule-based, not an LLM)",
    );
    await userEvent.click(toggle);
    const panel = screen.getByTestId("interpretation");
    expect(panel).toHaveTextContent("Arabian Sea");
    expect(panel).toHaveTextContent("0 to 100 dbar");
    expect(panel).toHaveTextContent("aggregate mean by month per profile");
    expect(panel).toHaveTextContent("region_alias:Arabian Sea");
    expect(screen.getByTestId("chat-result")).toBeInTheDocument();
    expect(screen.getByTestId("provenance")).toBeInTheDocument();
  });

  it("offers hint chips for a clarification and appends them to the draft", async () => {
    const user = {
      id: "m1",
      conversation_id: "c1",
      seq: 1,
      role: "user",
      kind: "user",
      text: "q",
      payload: {},
      correlation_id: null,
      created_at: "",
    };
    const clarification = message(
      "clarification",
      "Which time period should I use?",
      {
        interpretation: {
          ...INTERPRETATION,
          kind: "clarify",
          plan: null,
          clarification: {
            missing: ["time_range"],
            question: "Which time period should I use?",
          },
        },
        clarification: {
          missing: ["time_range"],
          question: "Which time period should I use?",
        },
      },
    );
    const stream = sse([
      ["conversation", { conversation_id: "c1", user_message: user }],
      ["message", clarification],
    ]);
    stubChat(stream, 200, [user, clarification]);
    renderWithProviders(<ChatPage />, "/chat");
    const input = await screen.findByLabelText("Your question");
    await userEvent.click(input);
    await userEvent.paste("temperature in the Arabian Sea");
    await userEvent.keyboard("{Enter}");
    await screen.findByText("Which time period should I use?");
    await userEvent.click(
      screen.getByRole("button", { name: "in January 2025" }),
    );
    expect(input).toHaveValue("in January 2025");
  });

  it("explains an unavailable assistant without hiding the rest of the app", async () => {
    stubChat(null, 503);
    renderWithProviders(<ChatPage />, "/chat");
    await userEvent.click(
      (
        await screen.findAllByRole("button", {
          name: /Monthly mean temperature/,
        })
      )[0],
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("temporarily unavailable");
    expect(alert).toHaveTextContent("[llm_unavailable]");
    expect(alert).toHaveTextContent("Correlation ID t-9");
    expect(screen.getByLabelText("Your question")).not.toBeDisabled();
  });
});
