import { afterEach, describe, expect, it, vi } from "vitest";
import { clientId, parseSse, streamMessage } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("parseSse", () => {
  it("parses complete blocks and keeps the unfinished remainder", () => {
    const text =
      'event: status\ndata: {"step": "plan"}\n\nevent: token\ndata: {"text": "The "}\n\nevent: tok';
    const { events, rest } = parseSse(text);
    expect(events).toEqual([
      { type: "status", data: { step: "plan" } },
      { type: "token", data: { text: "The " } },
    ]);
    expect(rest).toBe("event: tok");
  });

  it("drops malformed blocks and accepts CRLF", () => {
    const { events } = parseSse(
      'event: token\r\ndata: not json\r\n\r\nevent: message\r\ndata: {"kind":"answer"}\r\n\r\n',
    );
    expect(events).toEqual([{ type: "message", data: { kind: "answer" } }]);
  });
});

describe("clientId", () => {
  it("is generated once and reused", () => {
    const first = clientId();
    expect(first).toMatch(/^[A-Za-z0-9._:-]{1,64}$/);
    expect(clientId()).toBe(first);
  });
});

describe("streamMessage", () => {
  it("posts with the client header and delivers events in order", async () => {
    const body =
      'event: conversation\ndata: {"conversation_id": "c1", "user_message": {"id": "u1"}}\n\n' +
      'event: message\ndata: {"id": "m1", "kind": "answer"}\n\n';
    const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(
        (init?.headers as Record<string, string>)["X-FloatChat-Client"],
      ).toBe(clientId());
      expect((init?.headers as Record<string, string>).Accept).toBe(
        "text/event-stream",
      );
      expect(JSON.parse(String(init?.body))).toEqual({
        text: "hello",
        conversation_id: "c0",
      });
      return new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    });
    vi.stubGlobal("fetch", fetch);
    const seen: string[] = [];
    await streamMessage("hello", "c0", (event) => seen.push(event.type));
    expect(seen).toEqual(["conversation", "message"]);
  });

  it("throws the API error for a non-2xx answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: {
                code: "llm_unavailable",
                message: "The assistant is temporarily unavailable.",
                details: [],
                correlation_id: "t-1",
              },
            }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
    await expect(streamMessage("hello", null, () => {})).rejects.toMatchObject({
      status: 503,
      code: "llm_unavailable",
    });
  });
});
