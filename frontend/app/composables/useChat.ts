import type { ChatMessage, ActiveRun, StreamState } from "~/types/chat";

export interface ChatListItem {
  chat_id: string;
  title: string;
  repo: string;
  model?: string | null;
  updated_at: string;
  /** Set when the server has a live run for this chat (multi-chat in parallel). */
  active_run?: ActiveRun | null;
}

/** Mint a chat id in the same short format the backend uses. */
function generateChatId(): string {
  return crypto.randomUUID().slice(0, 12);
}

/**
 * Public chat API for components. Delegates streaming to useChatStreamManager;
 * this composable's job is to expose the currently visible chat (messages,
 * isStreaming) plus the list/load/delete operations.
 */
export function useChat() {
  const { apiFetch } = useApi();
  const streams = useChatStreamManager();

  // Which chat is currently shown. The URL (`/chat/:chatId`) is the source of
  // truth — `pages/chat/[[chatId]].vue` keeps this in sync so a page refresh
  // lands back on the same chat and re-attaches any live run.
  const activeChatId = useState<string | null>("activeChatId", () => null);

  const chatList = useState<ChatListItem[]>("chatList", () => []);
  const chatListLoading = ref(false);

  // Selections applied to the NEXT message sent.
  const selectedRepo = useState<string>("selectedRepo", () => "");
  const selectedModel = useState<string>("selectedModel", () => "");

  const messages = computed<ChatMessage[]>({
    get: () => streams.getMessages(activeChatId.value),
    set: (next) => {
      if (activeChatId.value) streams.setMessages(activeChatId.value, next);
    },
  });

  const currentStreamState = computed<StreamState>(() =>
    streams.getState(activeChatId.value),
  );
  const isStreaming = computed(() => streams.isStreaming(activeChatId.value));
  const isReconnecting = computed(
    () => currentStreamState.value.phase === "reconnecting",
  );
  const error = computed(() => currentStreamState.value.error);

  async function fetchChatList() {
    chatListLoading.value = true;
    try {
      chatList.value = await apiFetch<ChatListItem[]>("/api/chats");
      // Intentional: no eager stream attach here. The sidebar shows activity
      // via `active_run`; we attach lazily on loadChat so the assistant
      // placeholder lines up with the hydrated history.
    } catch {
      chatList.value = [];
    } finally {
      chatListLoading.value = false;
    }
  }

  /**
   * Sidebar indicator: either we're streaming locally, or the list response
   * flagged a server-side live run on this chat.
   *
   * Local stream state is authoritative when present: `active_run` on the
   * chatList item is a server snapshot taken at list-fetch time, so once we
   * observe a terminal phase locally we must ignore the stale flag (otherwise
   * the spinner keeps spinning until the next fetchChatList / page reload).
   */
  function chatHasActivity(chatId: string): boolean {
    const phase = streams.getState(chatId).phase;
    if (phase === "streaming" || phase === "reconnecting") return true;
    // Any non-idle phase means we have local truth — the run terminated.
    if (phase !== "idle") return false;
    // No local knowledge (e.g. run started in another tab): fall back to the
    // server's active_run hint from the last list fetch.
    const item = chatList.value.find((c) => c.chat_id === chatId);
    return !!item?.active_run?.run_id;
  }

  async function loadChat(chatId: string) {
    try {
      const data = await apiFetch<{
        chat_id: string;
        title: string;
        repo: string;
        model?: string | null;
        messages: {
          role: string;
          content: string;
          status?: string;
          tool_calls?: {
            name: string;
            id: string;
            input: Record<string, string>;
            output?: string;
            status: string;
          }[];
        }[];
        active_run?: ActiveRun | null;
      }>(`/api/chats/${chatId}`);

      activeChatId.value = chatId;
      if (data.repo) selectedRepo.value = data.repo;
      if (data.model) selectedModel.value = data.model;

      // Only repopulate messages if we don't already have a fresher in-memory
      // copy (a stream is still accumulating tokens for this chat).
      const state = streams.getState(chatId);
      const existingMsgs = streams.getMessages(chatId);
      const streamInFlight =
        state.phase === "streaming" || state.phase === "reconnecting";

      if (!streamInFlight || existingMsgs.length === 0) {
        const hydrated: ChatMessage[] = data.messages.map((m) => ({
          role: m.role as "user" | "assistant",
          content: m.content,
          status: (m.status as ChatMessage["status"]) || "complete",
          ...(m.tool_calls?.length
            ? {
                toolCalls: m.tool_calls.map((tc) => ({
                  name: tc.name,
                  input: tc.input || {},
                  output: tc.output,
                  status: (tc.status || "done") as "running" | "done" | "error",
                })),
              }
            : {}),
        }));
        streams.setMessages(chatId, hydrated);
      }

      if (data.active_run?.run_id && !streamInFlight) {
        await streams.attach(chatId, data.active_run.run_id);
      }
    } catch (err) {
      console.error("Chat konnte nicht geladen werden:", chatId);
      // Re-throw so route-level callers (pages/chat/[[chatId]].vue) can
      // redirect away from an invalid deep link.
      throw err;
    }
  }

  function newChat() {
    activeChatId.value = null;
  }

  async function deleteChat(chatId: string) {
    try {
      await apiFetch(`/api/chats/${chatId}`, { method: "DELETE" });
      chatList.value = chatList.value.filter((c) => c.chat_id !== chatId);
      streams.clearChat(chatId);
      if (activeChatId.value === chatId) newChat();
    } catch {
      // ignore
    }
  }

  async function sendMessage(query: string) {
    if (!query.trim()) return;
    if (isStreaming.value) return;

    // Mint a chat id locally for new chats so the UI and Mongo agree on the
    // id from the first keystroke — no bucket-migration dance needed.
    let chatId = activeChatId.value;
    if (!chatId) {
      chatId = generateChatId();
      activeChatId.value = chatId;
    }

    const history = streams
      .getMessages(chatId)
      .map((m) => ({ role: m.role, content: m.content }));

    await streams.startNew(chatId, {
      query,
      chatHistory: history,
      repo: selectedRepo.value || undefined,
      model: selectedModel.value || undefined,
    });

    // Refresh the sidebar so the new chat appears (or moves to top).
    fetchChatList();
  }

  async function cancelCurrent() {
    if (!activeChatId.value) return;
    await streams.cancel(activeChatId.value);
  }

  return {
    messages,
    isStreaming,
    isReconnecting,
    error,
    activeChatId,
    currentStreamState,
    chatList,
    chatListLoading,
    selectedRepo,
    selectedModel,
    sendMessage,
    cancelCurrent,
    fetchChatList,
    loadChat,
    newChat,
    deleteChat,
    chatHasActivity,
  };
}
