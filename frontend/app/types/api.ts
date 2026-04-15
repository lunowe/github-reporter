export interface RepoConnection {
  id: string;
  repo_full_name: string;
  display_name: string;
  default_branch: string;
}

export interface ChatRequest {
  query: string;
  chat_history: { role: string; content: string }[];
  repo?: string;
  model?: string;
}
