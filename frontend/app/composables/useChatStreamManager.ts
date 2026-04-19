/**
 * Chat stream manager — one registry for all in-flight chat runs.
 *
 * Each chat can own one streaming run at a time. The manager handles:
 *   - initial POST /api/chat (starts a run, streams it)
 *   - resume via GET /api/chat/{chat_id}/runs/{run_id}/stream (Last-Event-ID)
 *   - cancel via POST /api/chat/{chat_id}/runs/{run_id}/cancel
 *   - exponential-backoff reconnect on network errors
 *
 * State is scoped to Nuxt `useState` so it survives component unmounts
 * (switching chats doesn't kill an in-flight stream).
 */

import type {
  ChatMessage,
  SSEEvent,
  StreamState,
  StreamPhase,
  ToolCallState,
} from "~/types/chat";

const MAX_RECONNECT_ATTEMPTS = 8;
const BASE_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 30_000;

interface StreamPayload {
  query: string;
  repo?: string;
  model?: string;
  chatHistory: { role: string; content: string }[];
}

interface Controller {
  chatId: string;
  runId: string | null;
  lastEventId: string | null;
  abort: AbortController;
  reconnectAttempt: number;
  /** Index into the per-chat messages array where this run's assistant message lives. */
  assistantIdx: number;
  /** Tool calls keyed by tool call id so tool_result can resolve back to the call. */
  runningTools: Map<string, ToolCallState>;
  stopped: boolean;
}

export function useChatStreamManager() {
  const { apiBase, apiFetch } = useApi();

  const messagesByChat = useState<Record<string, ChatMessage[]>>(
    "chatMessagesByChat",
    () => ({}),
  );
  const streamStateByChat = useState<Record<string, StreamState>>(
    "chatStreamStateByChat",
    () => ({}),
  );

  // Controllers hold non-serializable fields (AbortController, Maps). They
  // live on `window` so they survive composable re-instantiation.
  const controllers = getControllerRegistry();

  // Reactive accessors — mutate in place; Vue's deep reactivity tracks it.

  function getMessages(chatId: string | null): ChatMessage[] {
    if (!chatId) return [];
    return messagesByChat.value[chatId] ?? [];
  }

  function setMessages(chatId: string, msgs: ChatMessage[]) {
    messagesByChat.value[chatId] = msgs;
  }

  function pushMessage(chatId: string, msg: ChatMessage): number {
    const bucket = messagesByChat.value;
    if (!bucket[chatId]) bucket[chatId] = [];
    const arr = bucket[chatId]!;
    arr.push(msg);
    return arr.length - 1;
  }

  function getMessageAt(chatId: string, index: number): ChatMessage | undefined {
    return messagesByChat.value[chatId]?.[index];
  }

  function getState(chatId: string | null): StreamState {
    if (!chatId) return emptyState();
    return streamStateByChat.value[chatId] ?? emptyState();
  }

  function setState(chatId: string, patch: Partial<StreamState>) {
    const current = streamStateByChat.value[chatId] ?? emptyState();
    streamStateByChat.value[chatId] = { ...current, ...patch };
  }

  function isStreaming(chatId: string | null): boolean {
    const p = getState(chatId).phase;
    return p === "streaming" || p === "reconnecting";
  }

  /**
   * Start a new chat turn for `chatId` (caller is responsible for generating
   * the chat id). Returns the assigned run_id once the POST headers arrive;
   * the stream continues in the background.
   */
  async function startNew(
    chatId: string,
    payload: StreamPayload,
  ): Promise<string | null> {
    // Paint the user turn + an empty assistant placeholder immediately.
    pushMessage(chatId, { role: "user", content: payload.query });
    const assistantIdx = pushMessage(chatId, {
      role: "assistant",
      content: "",
      toolCalls: [],
    });

    const controller = newController(chatId, assistantIdx);
    controllers.set(chatId, controller);
    setState(chatId, {
      phase: "streaming",
      runId: null,
      reconnectAttempt: 0,
      error: null,
    });

    let resp: Response;
    try {
      resp = await fetch(`${apiBase}/api/chat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        signal: controller.abort.signal,
        body: JSON.stringify({
          query: payload.query,
          chat_history: payload.chatHistory,
          chat_id: chatId,
          repo: payload.repo || undefined,
          model: payload.model || undefined,
        }),
      });
    } catch (err: any) {
      if (controller.abort.signal.aborted) return null;
      setState(chatId, { phase: "error", error: err?.message || "Verbindungsfehler" });
      controllers.delete(chatId);
      return null;
    }

    if (!resp.ok) {
      const txt = await resp.text().catch(() => "");
      setState(chatId, {
        phase: "error",
        error: `HTTP ${resp.status}${txt ? `: ${txt}` : ""}`,
      });
      controllers.delete(chatId);
      return null;
    }

    const runId = resp.headers.get("X-Run-Id");
    controller.runId = runId;
    setState(chatId, { runId });

    // Fire-and-forget; consumeSSE handles its own reconnect scheduling.
    void consumeSSE(controller, resp).catch((err) => {
      if (controller.abort.signal.aborted) return;
      if (controller.runId) {
        scheduleReconnect(controller);
      } else {
        setState(controller.chatId, {
          phase: "error",
          error: err?.message || "Streamfehler",
        });
        cleanup(controller);
      }
    });

    return runId;
  }

  /**
   * Attach to an existing run — e.g. a chat load reports an active_run, or
   * the user navigated back to a chat whose run we were already following.
   * Replays the buffer from the start so the assistant message rebuilds.
   */
  async function attach(chatId: string, runId: string): Promise<void> {
    const existing = controllers.get(chatId);
    if (existing && existing.runId === runId && !existing.stopped) return;

    const assistantIdx = pushMessage(chatId, {
      role: "assistant",
      content: "",
      toolCalls: [],
    });

    const controller = newController(chatId, assistantIdx);
    controller.runId = runId;
    controllers.set(chatId, controller);
    setState(chatId, {
      phase: "streaming",
      runId,
      reconnectAttempt: 0,
      error: null,
    });

    await openResumeStream(controller);
  }

  /** Cancel an in-flight run. Server persists the partial message. */
  async function cancel(chatId: string): Promise<void> {
    const controller = controllers.get(chatId);
    if (!controller || !controller.runId) return;
    try {
      await apiFetch(
        `/api/chat/${encodeURIComponent(chatId)}/runs/${encodeURIComponent(controller.runId)}/cancel`,
        { method: "POST" },
      );
    } catch {
      // The terminal event still comes through the stream.
    }
  }

  /** Stop reading the stream locally without cancelling server-side. */
  function detach(chatId: string): void {
    const controller = controllers.get(chatId);
    if (!controller) return;
    controller.stopped = true;
    controller.abort.abort();
    controllers.delete(chatId);
    setState(chatId, { phase: "idle", runId: null, reconnectAttempt: 0, error: null });
  }

  /** Reset the conversation buffer for a given chat (e.g. when deleted). */
  function clearChat(chatId: string): void {
    detach(chatId);
    delete messagesByChat.value[chatId];
    delete streamStateByChat.value[chatId];
  }

  async function consumeSSE(controller: Controller, resp: Response) {
    const reader = resp.body?.getReader();
    if (!reader) throw new Error("Response has no body");

    const decoder = new TextDecoder();
    let buffer = "";
    let currentId: string | null = null;
    let currentEvent: string | null = null;
    let currentData = "";

    try {
      while (true) {
        if (controller.abort.signal.aborted) break;
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        let nl: number;
        while ((nl = buffer.indexOf("\n")) !== -1) {
          const line = buffer.slice(0, nl).replace(/\r$/, "");
          buffer = buffer.slice(nl + 1);

          if (line === "") {
            if (currentData) {
              try {
                applyEvent(controller, JSON.parse(currentData) as SSEEvent, currentEvent);
              } catch {
                // ignore malformed
              }
            }
            if (currentId) controller.lastEventId = currentId;
            currentId = null;
            currentEvent = null;
            currentData = "";
            continue;
          }

          if (line.startsWith(":")) continue; // keepalive comment
          if (line.startsWith("id:")) {
            currentId = line.slice(3).trim();
          } else if (line.startsWith("event:")) {
            currentEvent = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            currentData += (currentData ? "\n" : "") + line.slice(5).trim();
          }
        }
      }
    } finally {
      try {
        reader.releaseLock();
      } catch {}
    }

    // Stream closed without a terminal event — assume transient failure.
    const phase = getState(controller.chatId).phase;
    if (
      !controller.stopped &&
      controller.runId &&
      (phase === "streaming" || phase === "reconnecting")
    ) {
      scheduleReconnect(controller);
    }
  }

  function applyEvent(
    controller: Controller,
    event: SSEEvent,
    eventName: string | null,
  ) {
    const type = (eventName as SSEEvent["type"]) || event.type;
    const msg = getMessageAt(controller.chatId, controller.assistantIdx);
    if (!msg) return;

    switch (type) {
      case "token": {
        if (event.content) msg.content = (msg.content || "") + event.content;
        break;
      }
      case "tool_call": {
        const tc: ToolCallState = {
          name: event.name || "unknown",
          input: event.input || {},
          status: "running",
        };
        if (event.id) controller.runningTools.set(event.id, tc);
        (msg.toolCalls ??= []).push(tc);
        break;
      }
      case "tool_result": {
        let target: ToolCallState | undefined;
        if (event.id) target = controller.runningTools.get(event.id);
        target ??= msg.toolCalls?.find(
          (tc) => tc.name === event.name && tc.status === "running",
        );
        if (target) {
          target.output = event.output;
          target.status = "done";
        }
        if (event.id) controller.runningTools.delete(event.id);
        break;
      }
      case "status": {
        applyStatusEvent(controller, msg, event);
        break;
      }
    }
  }

  function applyStatusEvent(
    controller: Controller,
    msg: ChatMessage,
    event: SSEEvent,
  ) {
    const s = event.status;
    if (s === "completed") {
      if (!msg.content && event.response) msg.content = event.response;
      msg.status = "complete";
      finalize(controller, "completed");
    } else if (s === "cancelled") {
      if (!msg.content && event.response) msg.content = event.response;
      msg.status = "cancelled";
      finalize(controller, "cancelled");
    } else if (s === "error" || s === "orphaned") {
      if (event.response) msg.content = msg.content || event.response;
      msg.status = "error";
      setState(controller.chatId, {
        phase: "error",
        error: event.error || "Agent-Fehler",
      });
      cleanup(controller);
    }
  }

  function finalize(controller: Controller, phase: StreamPhase) {
    setState(controller.chatId, { phase, reconnectAttempt: 0, error: null });
    cleanup(controller);
  }

  function cleanup(controller: Controller) {
    controller.stopped = true;
    controllers.delete(controller.chatId);
  }

  function scheduleReconnect(controller: Controller) {
    if (controller.stopped) return;
    if (controller.reconnectAttempt >= MAX_RECONNECT_ATTEMPTS) {
      setState(controller.chatId, {
        phase: "error",
        error: "Verbindung konnte nicht wiederhergestellt werden.",
      });
      cleanup(controller);
      return;
    }

    controller.reconnectAttempt += 1;
    const delay = Math.min(
      MAX_BACKOFF_MS,
      BASE_BACKOFF_MS * Math.pow(2, controller.reconnectAttempt - 1),
    );
    setState(controller.chatId, {
      phase: "reconnecting",
      reconnectAttempt: controller.reconnectAttempt,
    });

    setTimeout(() => {
      if (controller.stopped) return;
      controller.abort = new AbortController();
      openResumeStream(controller).catch(() => {
        // openResumeStream handles its own error path (re-schedules).
      });
    }, delay);
  }

  async function openResumeStream(controller: Controller) {
    if (!controller.runId) {
      setState(controller.chatId, {
        phase: "error",
        error: "Kein Run zum Wiederverbinden.",
      });
      cleanup(controller);
      return;
    }
    try {
      const url = `${apiBase}/api/chat/${encodeURIComponent(controller.chatId)}/runs/${encodeURIComponent(controller.runId)}/stream`;
      const headers: Record<string, string> = {};
      if (controller.lastEventId) headers["Last-Event-ID"] = controller.lastEventId;

      const resp = await fetch(url, {
        method: "GET",
        credentials: "include",
        signal: controller.abort.signal,
        headers,
      });

      if (resp.status === 410) {
        // Run expired — persisted final message is the source of truth.
        setState(controller.chatId, {
          phase: "error",
          error: "Die Antwort ist abgelaufen.",
        });
        cleanup(controller);
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      setState(controller.chatId, {
        phase: "streaming",
        reconnectAttempt: 0,
        error: null,
      });
      await consumeSSE(controller, resp);
    } catch {
      if (controller.abort.signal.aborted) return;
      scheduleReconnect(controller);
    }
  }

  return {
    messagesByChat,
    streamStateByChat,
    getMessages,
    setMessages,
    getState,
    isStreaming,
    startNew,
    attach,
    cancel,
    detach,
    clearChat,
  };
}

function newController(chatId: string, assistantIdx: number): Controller {
  return {
    chatId,
    runId: null,
    lastEventId: null,
    abort: new AbortController(),
    reconnectAttempt: 0,
    assistantIdx,
    runningTools: new Map(),
    stopped: false,
  };
}

function getControllerRegistry(): Map<string, Controller> {
  if (import.meta.server) return new Map();
  const key = "__ghr_chat_controllers__";
  const w = window as unknown as Record<string, unknown>;
  if (!w[key]) w[key] = new Map<string, Controller>();
  return w[key] as Map<string, Controller>;
}

function emptyState(): StreamState {
  return { runId: null, phase: "idle", reconnectAttempt: 0, error: null };
}
