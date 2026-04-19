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

export interface RateLimitBucket {
  limit: number;
  remaining: number;
  used: number;
  resets_at: string | null;
}

export interface RateLimitInfo {
  core: RateLimitBucket | null;
  search: RateLimitBucket | null;
  graphql: RateLimitBucket | null;
  fetched_at: string;
}

// ── Automations ────────────────────────────────────────────────────────

export interface AutomationStep {
  name: string;
  prompt: string;
  repo: string;
  model?: string | null;
}

export type FinalOutputFormat = "last_step" | "merge" | "template";

export interface Automation {
  id: string;
  name: string;
  description: string;
  steps: AutomationStep[];
  schedule_cron: string | null;
  timezone: string;
  enabled: boolean;
  email_enabled: boolean;
  email_to: string | null;
  model: string | null;
  final_output_format: FinalOutputFormat;
  final_output_template: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutomationStepResult {
  order: number;
  name: string;
  prompt: string;
  repo: string;
  output: string;
  duration_ms: number;
  error: string | null;
}

export interface AutomationRun {
  id: string;
  automation_id: string;
  automation_name: string;
  status: "queued" | "running" | "completed" | "failed";
  trigger: "manual" | "schedule";
  step_results: AutomationStepResult[];
  final_output: string;
  error: string | null;
  email_sent: boolean;
  started_at: string;
  completed_at: string | null;
}

export interface AutomationCreatePayload {
  name: string;
  description: string;
  steps: AutomationStep[];
  schedule_cron: string | null;
  timezone: string;
  enabled: boolean;
  email_enabled: boolean;
  email_to: string | null;
  model: string | null;
  final_output_format: FinalOutputFormat;
  final_output_template: string | null;
}

export interface EmailStatus {
  configured: boolean;
  default_to: string;
}
