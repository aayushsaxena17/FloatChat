import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import {
  ArrowUp,
  PanelLeftClose,
  PanelLeftOpen,
  SquarePen,
} from "lucide-react";
import { WaveMark } from "../components/WaveMark";
import { AssistantMessage, Problem } from "./AssistantMessage";
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
  classify: "Reading your question",
  retrieve: "Looking up the catalogue",
  plan: "Drafting the query plan",
  validate: "Checking the plan",
  execute: "Running the query",
  sanitise: "Checking the result",
  narrate: "Writing the answer",
};

/** How long a reloaded page keeps waiting for a reply the server may still be writing. */
const AWAIT_REPLY_MS = 120_000;

function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <article className="chat-message chat-user" data-kind="user">
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
  const [sidebar, setSidebar] = useState(true);
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
    if (input.current) input.current.style.height = "auto";
    void chat.send(text);
  };
  const hint = (text: string) => {
    setDraft((value) => (value ? `${value} ${text}` : text));
    input.current?.focus();
  };
  const busy = Boolean(chat.pending);
  const empty = chat.messages.length === 0 && !chat.pending;
  const last = chat.messages[chat.messages.length - 1];
  const awaiting = !busy && last?.role === "user";
  const lastAge = last ? Date.now() - Date.parse(last.created_at) : 0;
  const stillWriting = awaiting && lastAge < AWAIT_REPLY_MS;

  // A reloaded page may land before the server has finished the reply: keep asking for the
  // conversation for a while, then say so.
  useEffect(() => {
    if (!stillWriting) return;
    const timer = setInterval(() => void chat.detail.refetch(), 3000);
    return () => clearInterval(timer);
  }, [stillWriting, chat.detail]);

  return (
    <div className={`chat-shell${sidebar ? "" : " chat-shell-collapsed"}`}>
      <aside className="chat-sidebar" aria-label="Conversations">
        <div className="chat-sidebar-head">
          <button
            type="button"
            className="chat-icon-button"
            aria-label={sidebar ? "Hide conversations" : "Show conversations"}
            onClick={() => setSidebar((value) => !value)}
          >
            {sidebar ? (
              <PanelLeftClose size={16} aria-hidden="true" />
            ) : (
              <PanelLeftOpen size={16} aria-hidden="true" />
            )}
          </button>
          <button
            type="button"
            className="chat-icon-button"
            aria-label="New chat"
            title="New chat"
            onClick={() => chat.select(null)}
          >
            <SquarePen size={16} aria-hidden="true" />
          </button>
        </div>
        {sidebar ? (
          <nav className="chat-conversations" aria-label="Past conversations">
            {conversations.isPending ? (
              <p className="chat-sidebar-note">Loading…</p>
            ) : conversations.error ? (
              <p className="chat-sidebar-note">Conversations unavailable.</p>
            ) : conversations.data?.length === 0 ? (
              <p className="chat-sidebar-note">No conversations yet.</p>
            ) : (
              <ul>
                {(conversations.data ?? []).map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      aria-current={
                        row.id === chat.conversationId ? "true" : undefined
                      }
                      onClick={() => chat.select(row.id)}
                    >
                      {row.title || "Untitled"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </nav>
        ) : null}
      </aside>

      <section className="chat-main" aria-label="Conversation">
        <div className="chat-scroll">
          <div className="chat-column">
            {empty ? (
              <div className="chat-welcome">
                <h1>What would you like to know about the ocean?</h1>
                <p>
                  Ask about Argo temperature, salinity and pressure
                  observations. Give a period and an area; FloatChat asks when
                  either is missing instead of guessing.
                </p>
                <div
                  className="chat-suggestions"
                  role="group"
                  aria-label="Example questions"
                >
                  {SUGGESTIONS.map((text) => (
                    <button
                      key={text}
                      type="button"
                      onClick={() => void chat.send(text)}
                    >
                      {text}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            <div
              className="chat-thread"
              data-testid="chat-thread"
              aria-live="polite"
            >
              {chat.detail.isPending && chat.conversationId ? (
                <p className="chat-note" role="status">
                  Loading conversation…
                </p>
              ) : null}
              {chat.messages.map((message) =>
                message.role === "user" ? (
                  <UserMessage key={message.id} message={message} />
                ) : (
                  <AssistantMessage
                    key={message.id}
                    message={message}
                    onHint={hint}
                    onRetry={busy ? undefined : chat.retry}
                  />
                ),
              )}
              {chat.pending ? (
                <article
                  className="chat-message chat-assistant chat-pending"
                  data-kind="pending"
                >
                  {chat.pending.tokens ? (
                    <p className="chat-text">{chat.pending.tokens}</p>
                  ) : (
                    <p className="chat-step" role="status">
                      <WaveMark size={18} active />
                      {STEP_LABEL[chat.pending.step ?? ""] ?? chat.pending.step}
                      …
                    </p>
                  )}
                  {chat.pending.interpretation && !chat.pending.tokens ? (
                    <Interpretation data={chat.pending.interpretation} />
                  ) : null}
                </article>
              ) : null}
              {stillWriting ? (
                <p className="chat-step" role="status">
                  <WaveMark size={18} active />
                  Waiting for the reply…
                </p>
              ) : awaiting && last ? (
                <Problem
                  text="No reply was recorded for this message."
                  code="no_reply"
                  onRetry={() => void chat.send(last.text)}
                />
              ) : null}
              {chat.failure ? (
                <Problem
                  text={chat.failure.message}
                  code={chat.failure.code}
                  reference={chat.failure.correlationId}
                  onRetry={chat.lastText && !busy ? chat.retry : undefined}
                />
              ) : null}
              <div ref={end} />
            </div>
          </div>
        </div>

        <div className="chat-composer-wrap">
          <form className="chat-composer" onSubmit={submit}>
            <label htmlFor="chat-input" className="sr-only">
              Your question
            </label>
            <textarea
              id="chat-input"
              ref={input}
              value={draft}
              maxLength={2000}
              rows={1}
              placeholder="Ask about temperature, salinity or pressure in a region and period…"
              onChange={(event) => {
                setDraft(event.target.value);
                const element = event.target;
                element.style.height = "auto";
                element.style.height = `${Math.min(element.scrollHeight, 200)}px`;
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  if (draft.trim() && !busy) submit(event);
                }
              }}
              disabled={busy}
            />
            <button
              type="submit"
              className="chat-send"
              aria-label="Send"
              disabled={!draft.trim() || busy}
            >
              <ArrowUp size={18} aria-hidden="true" />
            </button>
          </form>
          <p className="chat-footnote">
            Numbers come from executed queries, never from the model. Times are
            UTC; depths are pressure in dbar.
          </p>
        </div>
      </section>
    </div>
  );
}
