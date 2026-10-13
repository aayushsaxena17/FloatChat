import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { useSearchParams } from "react-router";
import {
  ArrowUp,
  PanelLeftClose,
  PanelLeftOpen,
  SquarePen,
} from "lucide-react";
import { AssistantAvatar, AssistantMessage, Problem } from "./AssistantMessage";
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
  classify: "Reading your message",
  retrieve: "Looking through the catalogue",
  plan: "Thinking",
  validate: "Checking the query",
  execute: "Running the query",
  sanitise: "Checking the result",
  narrate: "Writing the answer",
};

/** How long a reloaded page keeps waiting for a reply the server may still be writing. */
const AWAIT_REPLY_MS = 120_000;
/** Within this many pixels of the bottom the thread follows new text; further up it stays put. */
const FOLLOW_PX = 96;

function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <article className="chat-message chat-user" data-kind="user">
      <p className="chat-text">{message.text}</p>
    </article>
  );
}

/** A retried question replaces its failed attempt, as a regenerated reply would: the thread
 * shows the question once, with its latest outcome. */
function withoutRetried(messages: ChatMessage[]): ChatMessage[] {
  const hidden = new Set<string>();
  messages.forEach((ask, index) => {
    if (ask.role !== "user") return;
    const next = messages[index + 1];
    const failed = next?.role === "assistant" && next.kind === "error";
    const again = failed ? messages[index + 2] : next;
    if (again?.role === "user" && again.text === ask.text) {
      hidden.add(ask.id);
      if (failed) hidden.add(next.id);
    }
  });
  return messages.filter((message) => !hidden.has(message.id));
}

function wideScreen() {
  return typeof window === "undefined" || !window.matchMedia
    ? true
    : !window.matchMedia("(max-width: 900px)").matches;
}

/** PRD 2.2 and 9.2: the conversational research interface over POST /v1/chat/messages. */
export function ChatPage() {
  const [params, setParams] = useSearchParams();
  const chat = useChat(params.get("conversation"));
  const conversations = useConversations();
  const [draft, setDraft] = useState("");
  const [sidebar, setSidebar] = useState(wideScreen);
  const input = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const following = useRef(true);

  useEffect(() => {
    const current = params.get("conversation");
    if (chat.conversationId && chat.conversationId !== current)
      setParams({ conversation: chat.conversationId }, { replace: true });
    if (!chat.conversationId && current) setParams({}, { replace: true });
  }, [chat.conversationId, params, setParams]);

  const messages = withoutRetried(chat.messages);
  const busy = Boolean(chat.pending);
  const empty = chat.messages.length === 0 && !chat.pending;
  const last = chat.messages[chat.messages.length - 1];
  const lastAsk = [...chat.messages]
    .reverse()
    .find((message) => message.role === "user");
  const awaiting = !busy && last?.role === "user";
  const lastAge = last ? Date.now() - Date.parse(last.created_at) : 0;
  const stillWriting = awaiting && lastAge < AWAIT_REPLY_MS;

  // The thread scrolls inside its own pane; it follows new text only while the reader is at
  // the bottom, so scrolling up to reread is never interrupted.
  useLayoutEffect(() => {
    const element = scroller.current;
    if (element && following.current) element.scrollTop = element.scrollHeight;
  }, [
    messages.length,
    chat.pending?.tokens,
    chat.pending?.step,
    chat.failure,
    stillWriting,
  ]);

  useEffect(() => {
    following.current = true;
  }, [chat.conversationId]);

  // A reloaded page may land before the server has finished the reply: keep asking for the
  // conversation for a while, then say so.
  useEffect(() => {
    if (!stillWriting) return;
    const timer = setInterval(() => void chat.detail.refetch(), 3000);
    return () => clearInterval(timer);
  }, [stillWriting, chat.detail]);

  const send = (text: string) => {
    following.current = true;
    void chat.send(text);
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.trim() || busy) return;
    const text = draft;
    setDraft("");
    if (input.current) input.current.style.height = "auto";
    send(text);
  };
  const hint = (text: string) => {
    setDraft((value) => (value ? `${value} ${text}` : text));
    input.current?.focus();
  };
  const startNew = () => {
    chat.select(null);
    setDraft("");
    input.current?.focus();
    if (!wideScreen()) setSidebar(false);
  };

  const composer = (
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
        autoFocus
        placeholder={
          empty
            ? "Ask about temperature, salinity or pressure…"
            : "Reply to FloatChat…"
        }
        onChange={(event) => {
          setDraft(event.target.value);
          const element = event.target;
          element.style.height = "auto";
          element.style.height = `${Math.min(element.scrollHeight, 220)}px`;
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit(event);
          }
        }}
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
  );

  return (
    <div className={`chat-shell${sidebar ? "" : " chat-shell-collapsed"}`}>
      <aside className="chat-sidebar" aria-label="Conversations">
        <div className="chat-sidebar-head">
          <button
            type="button"
            className="chat-icon-button"
            aria-label={sidebar ? "Hide conversations" : "Show conversations"}
            title={sidebar ? "Hide conversations" : "Show conversations"}
            onClick={() => setSidebar((value) => !value)}
          >
            {sidebar ? (
              <PanelLeftClose size={17} aria-hidden="true" />
            ) : (
              <PanelLeftOpen size={17} aria-hidden="true" />
            )}
          </button>
          {sidebar ? null : (
            <button
              type="button"
              className="chat-icon-button"
              aria-label="New chat"
              title="New chat"
              onClick={startNew}
            >
              <SquarePen size={17} aria-hidden="true" />
            </button>
          )}
        </div>
        {sidebar ? (
          <>
            <button type="button" className="chat-new" onClick={startNew}>
              <SquarePen size={16} aria-hidden="true" />
              New chat
            </button>
            <nav className="chat-conversations" aria-label="Past conversations">
              <p className="chat-sidebar-label">Recent</p>
              {conversations.isPending ? (
                <p className="chat-sidebar-note">Loading…</p>
              ) : conversations.error ? (
                <p className="chat-sidebar-note">
                  Conversations are unavailable.
                </p>
              ) : conversations.data?.length === 0 ? (
                <p className="chat-sidebar-note">No conversations yet.</p>
              ) : (
                <ul>
                  {(conversations.data ?? []).map((row) => (
                    <li key={row.id}>
                      <button
                        type="button"
                        title={row.title || "Untitled"}
                        aria-current={
                          row.id === chat.conversationId ? "true" : undefined
                        }
                        onClick={() => {
                          chat.select(row.id);
                          if (!wideScreen()) setSidebar(false);
                        }}
                      >
                        <span className="chat-conversation-title">
                          {row.title || "Untitled"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </nav>
          </>
        ) : null}
      </aside>

      <section
        className={`chat-main${empty ? " chat-main-empty" : ""}`}
        aria-label="Conversation"
      >
        <div
          className="chat-scroll"
          ref={scroller}
          onScroll={(event) => {
            const element = event.currentTarget;
            following.current =
              element.scrollHeight - element.scrollTop - element.clientHeight <
              FOLLOW_PX;
          }}
        >
          <div className="chat-column">
            {empty ? (
              <div className="chat-welcome">
                <span className="chat-welcome-mark" aria-hidden="true">
                  <AssistantAvatar />
                </span>
                <h1>What would you like to know about the ocean?</h1>
                <p>
                  Ask about Argo temperature, salinity and pressure in the
                  Indian Ocean. Say hello, ask what data is loaded, or name a
                  period and an area and FloatChat runs the query.
                </p>
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
              {messages.map((message) =>
                message.role === "user" ? (
                  <UserMessage key={message.id} message={message} />
                ) : (
                  <AssistantMessage
                    key={message.id}
                    message={message}
                    onHint={hint}
                    onRetry={
                      busy || message.id !== last?.id || !lastAsk
                        ? undefined
                        : () => send(lastAsk.text)
                    }
                  />
                ),
              )}
              {chat.pending ? (
                <article
                  className="chat-message chat-assistant chat-pending"
                  data-kind="pending"
                >
                  <AssistantAvatar active />
                  <div className="chat-body">
                    {chat.pending.tokens ? (
                      <p className="chat-text chat-streaming">
                        {chat.pending.tokens}
                      </p>
                    ) : (
                      <p className="chat-step" role="status">
                        {STEP_LABEL[chat.pending.step ?? ""] ??
                          chat.pending.step}
                        …
                      </p>
                    )}
                    {chat.pending.interpretation && !chat.pending.tokens ? (
                      <Interpretation data={chat.pending.interpretation} />
                    ) : null}
                  </div>
                </article>
              ) : null}
              {stillWriting ? (
                <article className="chat-message chat-assistant chat-pending">
                  <AssistantAvatar active />
                  <div className="chat-body">
                    <p className="chat-step" role="status">
                      Waiting for the reply…
                    </p>
                  </div>
                </article>
              ) : awaiting && last ? (
                <article className="chat-message chat-assistant">
                  <AssistantAvatar />
                  <div className="chat-body">
                    <Problem
                      text="This message never got a reply."
                      code="no_reply"
                      onRetry={() => send(last.text)}
                    />
                  </div>
                </article>
              ) : null}
              {chat.failure ? (
                <article className="chat-message chat-assistant">
                  <AssistantAvatar />
                  <div className="chat-body">
                    <Problem
                      text={chat.failure.message}
                      code={chat.failure.code}
                      reference={chat.failure.correlationId}
                      onRetry={chat.lastText && !busy ? chat.retry : undefined}
                    />
                  </div>
                </article>
              ) : null}
            </div>
          </div>
        </div>

        <div className="chat-composer-wrap">
          {composer}
          {empty ? (
            <div
              className="chat-suggestions"
              role="group"
              aria-label="Example questions"
            >
              {SUGGESTIONS.map((text) => (
                <button key={text} type="button" onClick={() => send(text)}>
                  {text}
                </button>
              ))}
            </div>
          ) : null}
          <p className="chat-footnote">
            Numbers come from executed queries, never from the model. Times are
            in UTC and depths are pressure in dbar.
          </p>
        </div>
      </section>
    </div>
  );
}
