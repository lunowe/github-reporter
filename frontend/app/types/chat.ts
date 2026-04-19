export type MessageStatus = "complete" | "partial" | "error" | "cancelled";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallState[];
  /** Set when the backend persisted the message with a non-complete status. */
  status?: MessageStatus;
}

export interface ToolCallState {
  name: string;
  input: Record<string, string>;
  output?: string;
  status: "running" | "done" | "error";
}

export interface SSEEvent {
  type: "status" | "tool_call" | "tool_result" | "token";
  status?: "started" | "completed" | "error" | "cancelled" | "orphaned";
  name?: string;
  id?: string;
  input?: Record<string, string>;
  output?: string;
  content?: string;
  response?: string;
  error?: string;
}

/** Per-chat stream state surfaced by useChatStreamManager. */
export type StreamPhase =
  | "idle"
  | "streaming"
  | "reconnecting"
  | "completed"
  | "cancelled"
  | "error";

export interface StreamState {
  runId: string | null;
  phase: StreamPhase;
  /** Increments on each reconnect attempt; useful for showing "retry 3/…" */
  reconnectAttempt: number;
  /** Human-readable error message for the "error" phase. */
  error: string | null;
}

/** Minimal info the server attaches when a chat has an in-flight run. */
export interface ActiveRun {
  run_id: string;
  status: string;
  started_at?: string;
}
