// Chat state: the server owns conversations and messages (PRD 14.3); this hook owns the
// in-flight stream (status steps, tokens, the interpretation and result before the message).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import type { QueryResponse } from "../api/types";
import {
  getConversation,
  listConversations,
  streamMessage,
  type ChatMessage,
  type Interpretation,
} from "./client";

export interface Pending {
  text: string;
  step: string | null;
  tokens: string;
  interpretation: Interpretation | null;
  result: QueryResponse | null;
}

export interface ChatFailure {
  code: string;
  message: string;
  status: number | null;
  correlationId: string | null;
}

export function describeFailure(error: unknown): ChatFailure {
  if (error instanceof ApiError)
    return {
      code: error.code,
      message: error.message,
      status: error.status,
      correlationId: error.correlationId,
    };
  if (error instanceof Error)
    return {
      code: "network",
      message: error.message,
      status: null,
      correlationId: null,
    };
  return {
    code: "unknown",
    message: "Request failed",
    status: null,
    correlationId: null,
  };
}

export function useConversations() {
  return useQuery({
    queryKey: ["chat", "conversations"],
    queryFn: ({ signal }) => listConversations(signal),
    staleTime: 30_000,
  });
}

export function useChat(initialConversation: string | null) {
  const client = useQueryClient();
  const [conversationId, setConversationId] = useState<string | null>(
    initialConversation,
  );
  const [local, setLocal] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState<Pending | null>(null);
  const [failure, setFailure] = useState<ChatFailure | null>(null);
  const abort = useRef<AbortController | null>(null);

  const detail = useQuery({
    queryKey: ["chat", "conversation", conversationId],
    queryFn: ({ signal }) => getConversation(conversationId as string, signal),
    enabled: conversationId !== null,
    staleTime: 60_000,
  });

  // Messages streamed in this session are appended to what the server returned; a refetch
  // of the detail replaces them with the stored rows.
  useEffect(() => {
    setLocal([]);
  }, [detail.data]);

  useEffect(() => () => abort.current?.abort(), []);

  const select = useCallback((id: string | null) => {
    abort.current?.abort();
    setPending(null);
    setFailure(null);
    setLocal([]);
    setConversationId(id);
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || pending) return;
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setFailure(null);
      setPending({
        text: trimmed,
        step: "sending",
        tokens: "",
        interpretation: null,
        result: null,
      });
      let streamedConversation = conversationId;
      try {
        await streamMessage(
          trimmed,
          conversationId,
          (event) => {
            if (event.type === "conversation") {
              streamedConversation = event.data.conversation_id;
              setConversationId(event.data.conversation_id);
              setLocal((rows) => [...rows, event.data.user_message]);
            } else if (event.type === "status") {
              setPending(
                (state) => state && { ...state, step: event.data.step },
              );
            } else if (event.type === "token") {
              setPending(
                (state) =>
                  state && { ...state, tokens: state.tokens + event.data.text },
              );
            } else if (event.type === "interpretation") {
              setPending(
                (state) => state && { ...state, interpretation: event.data },
              );
            } else if (event.type === "result") {
              setPending((state) => state && { ...state, result: event.data });
            } else if (event.type === "message") {
              setLocal((rows) => [...rows, event.data]);
            } else if (event.type === "error") {
              setFailure({
                code: event.data.code,
                message: event.data.message,
                status: null,
                correlationId: null,
              });
            }
          },
          controller.signal,
        );
      } catch (error) {
        if (!controller.signal.aborted) setFailure(describeFailure(error));
      } finally {
        if (abort.current === controller) {
          setPending(null);
          void client.invalidateQueries({
            queryKey: ["chat", "conversations"],
          });
          if (streamedConversation)
            void client.invalidateQueries({
              queryKey: ["chat", "conversation", streamedConversation],
            });
        }
      }
    },
    [client, conversationId, pending],
  );

  // Server rows first; rows streamed in this session are kept only until the server has them.
  const served = detail.data?.messages ?? [];
  const known = new Set(served.map((message) => message.id));
  const messages = [
    ...served,
    ...local.filter((message) => !known.has(message.id)),
  ];
  return { conversationId, messages, detail, pending, failure, send, select };
}
