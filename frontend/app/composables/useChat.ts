import type { ChatMessage, ToolCallState, SSEEvent } from "~/types/chat";

export interface ChatListItem {
  chat_id: string;
  title: string;
  repo: string;
  updated_at: string;
}

export function useChat() {
  const { apiBase, apiFetch } = useApi();

  const messages = useState<ChatMessage[]>("chatMessages", () => []);
  const isStreaming = ref(false);
  const currentToolCalls = ref<ToolCallState[]>([]);
  const error = ref<string | null>(null);

  // Current chat session
  const activeChatId = useState<string | null>("activeChatId", () => null);

  // Chat history list
  const chatList = useState<ChatListItem[]>("chatList", () => []);
  const chatListLoading = ref(false);

  // Selected repo & model
  const selectedRepo = useState<string>("selectedRepo", () => "");
  const selectedModel = useState<string>("selectedModel", () => "");

  // ── Fetch chat list ───────────────────────────────────────────────────

  async function fetchChatList() {
    chatListLoading.value = true;
    try {
      chatList.value = await apiFetch<ChatListItem[]>("/api/chats");
    } catch {
      chatList.value = [];
    } finally {
      chatListLoading.value = false;
    }
  }

  // ── Load existing chat ────────────────────────────────────────────────

  async function loadChat(chatId: string) {
    try {
      const data = await apiFetch<{
        chat_id: string;
        title: string;
        repo: string;
        messages: {
          role: string;
          content: string;
          tool_calls?: {
            name: string;
            id: string;
            input: Record<string, string>;
            output?: string;
            status: string;
          }[];
        }[];
      }>(`/api/chats/${chatId}`);

      activeChatId.value = chatId;
      if (data.repo) selectedRepo.value = data.repo;
      messages.value = data.messages.map((m) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
        // Restore tool calls from DB if present
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
    } catch {
      error.value = "Chat konnte nicht geladen werden.";
    }
  }

  // ── Start new chat ────────────────────────────────────────────────────

  function newChat() {
    activeChatId.value = null;
    messages.value = [];
    error.value = null;
  }

  // ── Delete chat ───────────────────────────────────────────────────────

  async function deleteChat(chatId: string) {
    try {
      await apiFetch(`/api/chats/${chatId}`, { method: "DELETE" });
      chatList.value = chatList.value.filter((c) => c.chat_id !== chatId);
      if (activeChatId.value === chatId) {
        newChat();
      }
    } catch {
      // ignore
    }
  }

  // ── Send message ──────────────────────────────────────────────────────

  async function sendMessage(query: string) {
    if (!query.trim() || isStreaming.value) return;

    error.value = null;
    isStreaming.value = true;
    currentToolCalls.value = [];

    messages.value.push({ role: "user", content: query });

    const assistantMsg: ChatMessage = {
      role: "assistant",
      content: "",
      toolCalls: [],
    };
    messages.value.push(assistantMsg);
    const assistantIdx = messages.value.length - 1;

    try {
      const history = messages.value
        .slice(0, -2)
        .map((m) => ({ role: m.role, content: m.content }));

      const response = await fetch(`${apiBase}/api/chat`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query,
          chat_history: history,
          chat_id: activeChatId.value || undefined,
          repo: selectedRepo.value || undefined,
          model: selectedModel.value || undefined,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      // Capture chat_id from response header (new chats)
      const responseChatId = response.headers.get("X-Chat-Id");
      if (responseChatId) {
        activeChatId.value = responseChatId;
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const jsonStr = line.slice(6).trim();
          if (!jsonStr) continue;

          try {
            const event: SSEEvent = JSON.parse(jsonStr);
            processEvent(event, assistantIdx);
          } catch {
            // Ignore malformed lines
          }
        }
      }

      // Refresh chat list after a successful message
      fetchChatList();
    } catch (e: any) {
      error.value = e.message || "Verbindungsfehler";
      if (!messages.value[assistantIdx]?.content) {
        messages.value.splice(assistantIdx, 1);
      }
    } finally {
      isStreaming.value = false;
      currentToolCalls.value = [];
    }
  }

  function processEvent(event: SSEEvent, assistantIdx: number) {
    const msg = messages.value[assistantIdx];
    if (!msg) return;

    switch (event.type) {
      case "tool_call": {
        const tc: ToolCallState = {
          name: event.name || "unknown",
          input: event.input || {},
          status: "running",
        };
        currentToolCalls.value.push(tc);
        if (!msg.toolCalls) msg.toolCalls = [];
        msg.toolCalls.push(tc);
        break;
      }

      case "tool_result": {
        const running = currentToolCalls.value.find(
          (t) => t.name === event.name && t.status === "running"
        );
        if (running) {
          running.output = event.output;
          running.status = "done";
        }
        break;
      }

      case "token":
        if (event.content) {
          msg.content += event.content;
        }
        break;

      case "status":
        if (event.status === "completed" && event.response) {
          if (!msg.content) {
            msg.content = event.response;
          }
        }
        if (event.status === "error") {
          error.value = event.error || "Agent-Fehler";
        }
        break;
    }
  }

  function clearMessages() {
    activeChatId.value = null;
    messages.value = [];
  }

  return {
    messages,
    isStreaming,
    currentToolCalls,
    error,
    activeChatId,
    chatList,
    chatListLoading,
    selectedRepo,
    selectedModel,
    sendMessage,
    clearMessages,
    fetchChatList,
    loadChat,
    newChat,
    deleteChat,
  };
}
