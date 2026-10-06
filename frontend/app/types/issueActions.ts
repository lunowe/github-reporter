/**
 * Issue drafts proposed by the chat agent.
 *
 * The agent never writes to GitHub directly: a "propose_*" tool stores a
 * draft on the server, the chat renders it as a confirmation card, and only
 * when the user confirms does the server perform the write.
 */

export type IssueActionKind = "create_issue" | "update_issue" | "comment";

export type IssueActionStatus =
  | "pending"
  | "applying"
  | "applied"
  | "rejected"
  | "failed";

export type IssueState = "open" | "closed";
export type IssueStateReason = "completed" | "not_planned" | "reopened";

/** Why this account can't apply drafts, if it can't. */
export type IssueActionReadOnlyReason = "viewer" | "suspended";

/** Server-side limits, mirrored here so the card can validate before apply. */
export const ISSUE_TITLE_MAX = 256;
export const ISSUE_BODY_MAX = 65_000;

/** Only the fields the agent wants to set. */
export interface IssueActionProposed {
  title?: string;
  /** GitHub-flavoured markdown. */
  body?: string;
  labels?: string[];
  assignees?: string[];
  state?: IssueState;
  state_reason?: IssueStateReason;
}

/** Snapshot of the target issue at proposal time (update/comment only). */
export interface IssueActionCurrent {
  title: string;
  body: string;
  labels: string[];
  assignees: string[];
  state: IssueState;
  html_url: string;
}

export interface IssueActionResult {
  issue_number: number;
  html_url: string;
  comment_url?: string;
  /**
   * German, human-readable. Set when GitHub applied the write but silently
   * dropped parts of it (e.g. labels/assignees without triage rights).
   */
  warning?: string;
}

export interface IssueAction {
  action_id: string;
  kind: IssueActionKind;
  /** "owner/name" */
  repo: string;
  /** Target issue for update/comment; null for create. */
  issue_number: number | null;
  status: IssueActionStatus;
  proposed: IssueActionProposed;
  current: IssueActionCurrent | null;
  /** Set when applied. */
  result: IssueActionResult | null;
  /**
   * German, human-readable. Set when failed — or, while still pending, when
   * the last apply hit a fixable problem (missing permission, rate limit,
   * GitHub outage) and the draft may be retried.
   */
  error: string | null;
  /** False e.g. for read-only viewer accounts. */
  can_apply: boolean;
  /** Set when `can_apply` is false because of the account itself. */
  read_only_reason: IssueActionReadOnlyReason | null;
  created_at: string;
  updated_at: string;
}

/** User edits made in the card before confirming. */
export interface IssueActionEdits {
  title?: string;
  body?: string;
}

/**
 * Bodies longer than this are only shown to the agent truncated, so the
 * backend refuses full replacements — editing such a body here can't succeed.
 */
export const ISSUE_BODY_REPLACE_MAX = 20_000;

/** Length as the backend (Python) counts it: code points, not UTF-16 units. */
export function charLength(text: string): number {
  return [...text].length;
}
