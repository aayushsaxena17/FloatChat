// Chat API client (plan W6): the client identifier, the conversation reads and the streamed
// message over fetch. EventSource cannot POST, so the server-sent events are parsed here.
import { ApiError, buildUrl, CORRELATION_HEADER } from "../api/client";
import type { components } from "../api/schema";
import type { QueryResponse } from "../api/types";

export const CLIENT_HEADER = "X-FloatChat-Client";
const CLIENT_KEY = "floatchat.client";

export type ChatMessage = components["schemas"]["ChatMessage"];
export type ChatConversation = components["schemas"]["ChatConversation"];
export type ChatAnswer = components["schemas"]["ChatAnswer"];
export type ConversationDetail = components["schemas"]["ConversationDetail"];

/** The audit view the pipeline attaches to every assistant message (plan section 5). */
export interface Interpretation {
  classification?: string;
  kind?: string;
  provider?: string;
  model?: string;
  model_version?: string | null;
  prompt_version?: string;
  narrator_version?: string;
  embedding_model?: string;
  retrieval_mode?: string;
  retrieved?: Array<{
    id: string;
    doc_type: string;
    title: string;
    score: number;
  }>;
  examples?: Array<{
    id: string;
    doc_type: string;
    title: string;
    score: number;
  }>;
  reference_time?: string;
  plan?: Record<string, unknown> | null;
  plan_sha256?: string | null;
  clarification?: { missing: string[]; question: string } | null;
  reason?: string | null;
  validation?: Array<{ field: string; code: string; message: string }>;
  timings?: Record<string, number>;
  tokens?: Record<string, number>;
  transformation?: string | null;
  narrative_source?: string;
  narrative_rejected?: boolean;
  execution_error?: string;
  narration_error?: string;
  engine_interpretation?: Record<string, unknown>;
}

export interface MessagePayload {
  interpretation?: Interpretation;
  /** Stage 5 (ADR-0081): the export request the assistant offers to run as a job. */
  job_offer?: Record<string, unknown>;
  plan?: Record<string, unknown>;
  result?: QueryResponse;
  result_omitted?: boolean;
  clarification?: { missing: string[]; question: string };
  code?: string;
}

export function payloadOf(message: ChatMessage): MessagePayload {
  return (message.payload ?? {}) as MessagePayload;
}

function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto)
    return crypto.randomUUID();
  return `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** The opaque client identifier (ADR-0072), kept per browser; Stage 7 maps it to a user. */
export function clientId(): string {
  try {
    const stored = localStorage.getItem(CLIENT_KEY);
    if (stored && /^[A-Za-z0-9._:-]{1,64}$/.test(stored)) return stored;
    const fresh = randomId();
    localStorage.setItem(CLIENT_KEY, fresh);
    return fresh;
  } catch {
    return randomId();
  }
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return { Accept: "application/json", [CLIENT_HEADER]: clientId(), ...extra };
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const parsed: unknown = await response.json().catch(() => null);
    const envelope =
      parsed && typeof parsed === "object" && "error" in parsed
        ? (parsed as ApiError["envelope"])
        : null;
    throw new ApiError(
      response.status,
      envelope,
      response.headers.get(CORRELATION_HEADER),
    );
  }
  return (await response.json()) as T;
}

export async function listConversations(
  signal?: AbortSignal,
): Promise<ChatConversation[]> {
  const response = await fetch(buildUrl("/chat/conversations"), {
    headers: headers(),
    signal,
  });
  const body = await readJson<{ conversations: ChatConversation[] }>(response);
  return body.conversations;
}

export async function getConversation(
  id: string,
  signal?: AbortSignal,
): Promise<ConversationDetail> {
  const response = await fetch(
    buildUrl(`/chat/conversations/${encodeURIComponent(id)}`),
    { headers: headers(), signal },
  );
  return readJson<ConversationDetail>(response);
}

export type ChatEvent =
  | {
      type: "conversation";
      data: { conversation_id: string; user_message: ChatMessage };
    }
  | { type: "status"; data: { step: string } }
  | { type: "interpretation"; data: Interpretation }
  | { type: "result"; data: QueryResponse }
  | { type: "token"; data: { text: string } }
  | { type: "message"; data: ChatMessage }
  | { type: "error"; data: { code: string; message: string } };

/** Parses complete `event:`/`data:` blocks; returns the events and the unconsumed remainder. */
export function parseSse(buffer: string): {
  events: ChatEvent[];
  rest: string;
} {
  const events: ChatEvent[] = [];
  const normalised = buffer.replace(/\r\n/g, "\n");
  const blocks = normalised.split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let type = "";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) type = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trim());
    }
    if (!type || data.length === 0) continue;
    try {
      events.push({ type, data: JSON.parse(data.join("\n")) } as ChatEvent);
    } catch {
      // A malformed block is dropped; the final message carries the authoritative state.
    }
  }
  return { events, rest };
}

/** POST a message and deliver every server-sent event to `onEvent` as it arrives. */
export async function streamMessage(
  text: string,
  conversationId: string | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(buildUrl("/chat/messages"), {
    method: "POST",
    headers: headers({
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    }),
    body: JSON.stringify({
      text,
      conversation_id: conversationId ?? undefined,
    }),
    signal,
  });
  if (!response.ok) {
    await readJson(response);
    return;
  }
  const reader = response.body?.getReader();
  if (!reader) {
    const whole = await response.text();
    for (const event of parseSse(whole + "\n\n").events) onEvent(event);
    return;
  }
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSse(buffer);
    buffer = parsed.rest;
    for (const event of parsed.events) onEvent(event);
  }
  for (const event of parseSse(buffer + "\n\n").events) onEvent(event);
}
