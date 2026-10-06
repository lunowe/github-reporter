import type { ToolCallState } from "~/types/chat";
import type { IssueAction, IssueActionEdits } from "~/types/issueActions";

/**
 * Issue actions composable — fetch, apply, and reject agent-proposed drafts.
 */
export function useIssueActions() {
  const { apiFetch } = useApi();

  async function getAction(actionId: string): Promise<IssueAction> {
    return await apiFetch<IssueAction>(`/api/issue-actions/${actionId}`);
  }

  async function applyAction(
    actionId: string,
    edits: IssueActionEdits = {},
  ): Promise<IssueAction> {
    return await apiFetch<IssueAction>(
      `/api/issue-actions/${actionId}/apply`,
      { method: "POST", body: edits },
    );
  }

  async function rejectAction(actionId: string): Promise<IssueAction> {
    return await apiFetch<IssueAction>(
      `/api/issue-actions/${actionId}/reject`,
      { method: "POST" },
    );
  }

  return { getAction, applyAction, rejectAction };
}

// ── Tool-call helpers ──────────────────────────────────────────────────

/** Tool names whose successful output references a stored draft. */
export const ISSUE_ACTION_TOOLS = new Set([
  "propose_create_issue",
  "propose_update_issue",
  "propose_issue_comment",
]);

/**
 * Returns the draft id a finished propose_* call points to, or null when the
 * call is still running, failed, or isn't a propose tool at all (in which
 * case the generic tool row is the right thing to show).
 */
export function issueActionIdFromToolCall(tc: ToolCallState): string | null {
  if (!ISSUE_ACTION_TOOLS.has(tc.name) || tc.status !== "done" || !tc.output) {
    return null;
  }
  try {
    const parsed = JSON.parse(tc.output);
    return typeof parsed?.action_id === "string" ? parsed.action_id : null;
  } catch {
    return null;
  }
}

/** How a propose_* tool reports that it stored nothing. */
const PROPOSE_FAILED_PREFIX = "Kein Entwurf erstellt:";

/**
 * Returns why a finished propose_* call produced no draft (e.g. an unknown
 * label), or null when it did produce one, is still running, or isn't a
 * propose tool. The chat shows this instead of a card, so the user sees why
 * nothing appeared.
 */
export function issueActionFailureFromToolCall(tc: ToolCallState): string | null {
  if (!ISSUE_ACTION_TOOLS.has(tc.name) || tc.status !== "done" || !tc.output) {
    return null;
  }
  if (issueActionIdFromToolCall(tc)) return null;
  const output = tc.output.trim();
  if (output.startsWith(PROPOSE_FAILED_PREFIX)) {
    return output.slice(PROPOSE_FAILED_PREFIX.length).trim() || "Kein Grund angegeben.";
  }
  return output || "Kein Grund angegeben.";
}

// ── Error helpers ──────────────────────────────────────────────────────

/**
 * Human-readable message from a FastAPI error (`detail` is a string or
 * `{ message }`), falling back to the fetch error itself.
 */
export function issueActionErrorMessage(e: unknown, fallback: string): string {
  const err = e as { data?: { detail?: unknown }; message?: string } | null;
  const detail = err?.data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (
    detail &&
    typeof detail === "object" &&
    typeof (detail as { message?: unknown }).message === "string"
  ) {
    return (detail as { message: string }).message;
  }
  return err?.message || fallback;
}

/** HTTP status of a failed fetch, if known. */
export function issueActionErrorStatus(e: unknown): number | null {
  const err = e as { statusCode?: number; status?: number } | null;
  return err?.statusCode ?? err?.status ?? null;
}
