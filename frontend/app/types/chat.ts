export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallState[];
}

export interface ToolCallState {
  name: string;
  input: Record<string, string>;
  output?: string;
  status: "running" | "done" | "error";
}

export interface SSEEvent {
  type: "status" | "tool_call" | "tool_result" | "token";
  status?: "started" | "completed" | "error";
  name?: string;
  input?: Record<string, string>;
  output?: string;
  content?: string;
  response?: string;
  error?: string;
}
