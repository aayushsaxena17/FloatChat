import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { MessageSquare, Plus, SendHorizontal } from "lucide-react";
import { Button } from "../components/ui/button";
import { StatusMessage } from "../components/StatusMessage";
import { AssistantMessage } from "./AssistantMessage";
import { Interpretation } from "./Interpretation";
import type { ChatMessage } from "./client";
import { useChat, useConversations } from "./useChat";

const SUGGESTIONS = [
  "Monthly mean temperature in the Arabian Sea from January to March 2025 in the upper 100 dbar",
  "How many profiles were there in the Bay of Bengal in February 2025?",
  "T-S diagram for the 10 newest profiles in the Laccadive Sea in March 2025",
  "Which 3 floats are nearest to 15N 65E in January 2025?",
];

const STEP_LABEL: Record<string, string> = {
  sending: "Sending",
  classify: "Classifying the request",
  retrieve: "Retrieving catalogue and region documents",
  plan: "Drafting a query plan",
  validate: "Validating the plan against the catalogue",
  execute: "Running the validated query",
  sanitise: "Checking the result",
  narrate: "Writing the answer",
};

function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <article className="chat-message chat-user" data-kind="user">
      <header>
        <span className="chat-role">You</span>
      </header>
      <p className="chat-text">{message.text}</p>
    </article>
  );
}

/** PRD 2.2 and 9.2: the conversational research interface over POST /v1/chat/messages. */
export function ChatPage() {
  const [params, setParams] = useSearchParams();
  const chat = useChat(params.get("conversation"));
  const conversations = useConversations();
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const current = params.get("conversation");
    if (chat.conversationId && chat.conversationId !== current)
      setParams({ conversation: chat.conversationId }, { replace: true });
    if (!chat.conversationId && current) setParams({}, { replace: true });
  }, [chat.conversationId, params, setParams]);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [chat.messages.length, chat.pending?.tokens, chat.pending?.step]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft;
    setDraft("");
    void chat.send(text);
  };
  const hint = (text: string) => {
    setDraft((value) => (value ? `${value} ${text}` : text));
    input.current?.focus();
  };
  const unavailable =
    chat.failure &&
    (chat.failure.code === "llm_unavailable" ||
      chat.failure.code === "llm_budget_exhausted");

  return (
    <>
      <div className="page-heading explorer-heading">
        <div>
          <p className="eyebrow">THE OBSERVATORY / CONVERSATIONAL RESEARCH</p>
          <h1>Chat</h1>
          <p className="page-description">
            Ask in plain language; every answer shows the validated query plan
            it ran.
          </p>
        </div>
      </div>
      <div className="chat-layout">
        <aside className="panel chat-sidebar" aria-label="Conversations">
          <div className="chat-sidebar-head">
            <h2>Conversations</h2>
            <Button
              variant="outline"
              size="xs"
              onClick={() => chat.select(null)}
            >
              <Plus aria-hidden="true" />
              New
            </Button>
          </div>
          <StatusMessage
            loading={conversations.isPending}
            error={conversations.error}
            empty={conversations.data?.length === 0 && "No conversations yet."}
          >
            <ul className="chat-conversations">
              {(conversations.data ?? []).map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    aria-current={
                      row.id === chat.conversationId ? "true" : undefined
                    }
                    onClick={() => chat.select(row.id)}
                  >
                    <MessageSquare size={13} aria-hidden="true" />
                    <span>{row.title || "Untitled"}</span>
                    <small>{row.message_count}</small>
                  </button>
                </li>
              ))}
            </ul>
          </StatusMessage>
        </aside>
        <section className="chat-main" aria-label="Conversation">
          <div
            className="chat-thread"
            data-testid="chat-thread"
            aria-live="polite"
          >
            {chat.detail.isPending && chat.conversationId ? (
              <p className="status" role="status">
                Loading conversation…
              </p>
            ) : null}
            {chat.messages.length === 0 && !chat.pending ? (
              <div className="chat-empty">
                <p>
                  Ask about Argo temperature, salinity and pressure
                  observations. Give a period and an area; FloatChat asks when
                  either is missing instead of guessing.
                </p>
                <div
                  className="chat-chips"
                  role="group"
                  aria-label="Example questions"
                >
                  {SUGGESTIONS.map((text) => (
                    <button
                      key={text}
                      type="button"
                      className="chat-chip"
                      onClick={() => void chat.send(text)}
                    >
                      {text}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            {chat.messages.map((message) =>
              message.role === "user" ? (
                <UserMessage key={message.id} message={message} />
              ) : (
                <AssistantMessage
                  key={message.id}
                  message={message}
                  onHint={hint}
                />
              ),
            )}
            {chat.pending ? (
              <article
                className="chat-message chat-assistant chat-pending"
                data-kind="pending"
              >
                <header>
                  <span className="chat-role">FloatChat</span>
                  <span className="chat-step" role="status">
                    {STEP_LABEL[chat.pending.step ?? ""] ?? chat.pending.step}…
                  </span>
                </header>
                {chat.pending.tokens ? (
                  <p className="chat-text">{chat.pending.tokens}</p>
                ) : null}
                {chat.pending.interpretation && !chat.pending.tokens ? (
                  <Interpretation data={chat.pending.interpretation} />
                ) : null}
              </article>
            ) : null}
            {chat.failure ? (
              <p className="status" data-kind="error" role="alert">
                {unavailable
                  ? "The assistant is temporarily unavailable; the dashboard, map and profile views keep working."
                  : chat.failure.message}{" "}
                [{chat.failure.code}]
                {chat.failure.correlationId
                  ? ` Correlation ID ${chat.failure.correlationId}.`
                  : ""}
              </p>
            ) : null}
            <div ref={end} />
          </div>
          <form className="chat-composer" onSubmit={submit}>
            <label htmlFor="chat-input" className="sr-only">
              Your question
            </label>
            <textarea
              id="chat-input"
              ref={input}
              value={draft}
              maxLength={2000}
              rows={2}
              placeholder="For example: monthly mean salinity in the Bay of Bengal in February 2025"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  if (draft.trim() && !chat.pending) submit(event);
                }
              }}
              disabled={Boolean(chat.pending)}
            />
            <Button
              type="submit"
              disabled={!draft.trim() || Boolean(chat.pending)}
            >
              <SendHorizontal aria-hidden="true" />
              Send
            </Button>
          </form>
          <p className="chat-footnote">
            Numbers come from executed queries, never from the model. Times are
            UTC; depths are pressure in dbar.
          </p>
        </section>
      </div>
    </>
  );
}
