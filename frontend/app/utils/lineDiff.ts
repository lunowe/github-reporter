import { diffLines } from "diff";

/**
 * Line-level diff of an issue body, shaped for display: changed lines stay
 * visible, long unchanged stretches fold into a single "n unchanged lines"
 * row, and the stats say whether the edit throws away a lot of text.
 */

export type DiffRow =
  | { kind: "ctx" | "add" | "del"; text: string }
  /** A folded run of unchanged lines; `lines` lets the view unfold it. */
  | { kind: "fold"; lines: string[] };

export interface LineDiff {
  rows: DiffRow[];
  added: number;
  removed: number;
  /** Line count of the old text (0 for an empty body). */
  oldLines: number;
  /** True when the edit removes a large share of the old text. */
  destructive: boolean;
  /** No differing lines at all. */
  identical: boolean;
  /** The exact diff was too expensive; rows/counts come from a line-set comparison. */
  approximate: boolean;
}

/** Unchanged lines kept visible on each side of a change. */
const CONTEXT = 3;
/** Fold only when it saves more than this many lines — a 2-line fold is noise. */
const MIN_FOLD = 4;

/** Lines removed beyond which the edit is treated as destructive. */
const DESTRUCTIVE_LINES = 20;
/** Share of the old text (lines or characters) beyond which it's destructive. */
const DESTRUCTIVE_RATIO = 0.3;
/** Budget for the exact diff; Myers is quadratic on very different long texts. */
const DIFF_TIMEOUT_MS = 100;

function splitLines(text: string): string[] {
  if (!text) return [];
  const lines = text.split("\n");
  // A trailing newline isn't an extra empty line
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}

export function computeLineDiff(oldText: string, newText: string): LineDiff {
  const oldNorm = (oldText ?? "").replace(/\r\n?/g, "\n");
  const newNorm = (newText ?? "").replace(/\r\n?/g, "\n");

  const oldLines = splitLines(oldNorm).length;

  if (oldNorm === newNorm) {
    return {
      rows: [],
      added: 0,
      removed: 0,
      oldLines,
      destructive: false,
      identical: true,
      approximate: false,
    };
  }

  // Flatten the change objects into one line per row
  const flat: { kind: "ctx" | "add" | "del"; text: string }[] = [];
  let added = 0;
  let removed = 0;
  let removedChars = 0;
  const exact = diffLines(oldNorm, newNorm, { timeout: DIFF_TIMEOUT_MS });
  const approximate = exact === undefined;
  for (const change of exact ?? approximateChanges(oldNorm, newNorm)) {
    const kind = change.added ? "add" : change.removed ? "del" : "ctx";
    for (const line of splitLines(change.value)) {
      flat.push({ kind, text: line });
    }
    if (kind === "add") added += change.count ?? 0;
    if (kind === "del") {
      removed += change.count ?? 0;
      removedChars += change.value.length;
    }
  }

  // Fold unchanged runs that are longer than context-on-both-sides + MIN_FOLD
  const rows: DiffRow[] = [];
  let i = 0;
  while (i < flat.length) {
    const row = flat[i]!;
    if (row.kind !== "ctx") {
      rows.push(row);
      i++;
      continue;
    }
    let j = i;
    while (j < flat.length && flat[j]!.kind === "ctx") j++;
    const run = flat.slice(i, j);
    const leadingContext = i === 0 ? 0 : CONTEXT;
    const trailingContext = j === flat.length ? 0 : CONTEXT;
    const foldable = run.length - leadingContext - trailingContext;
    if (foldable >= MIN_FOLD) {
      rows.push(...run.slice(0, leadingContext));
      rows.push({
        kind: "fold",
        lines: run.slice(leadingContext, run.length - trailingContext).map((r) => r.text),
      });
      rows.push(...run.slice(run.length - trailingContext));
    } else {
      rows.push(...run);
    }
    i = j;
  }

  const oldChars = oldNorm.length;
  const destructive =
    removed > DESTRUCTIVE_LINES ||
    (oldLines > 0 && removed / oldLines > DESTRUCTIVE_RATIO) ||
    (oldChars > 0 && removedChars / oldChars > DESTRUCTIVE_RATIO);

  return { rows, added, removed, oldLines, destructive, identical: false, approximate };
}

/**
 * Linear fallback: lines that only exist in the old text count as removed,
 * lines only in the new text as added (multiset comparison, order ignored).
 * Good enough for the counts and the destructive warning on huge bodies.
 */
function approximateChanges(oldText: string, newText: string) {
  const remaining = new Map<string, number>();
  for (const line of splitLines(newText)) remaining.set(line, (remaining.get(line) ?? 0) + 1);
  const removedLines: string[] = [];
  for (const line of splitLines(oldText)) {
    const n = remaining.get(line) ?? 0;
    if (n > 0) remaining.set(line, n - 1);
    else removedLines.push(line);
  }
  const addedLines = [...remaining].flatMap(([line, n]) => Array<string>(n).fill(line));
  const asChange = (lines: string[], key: "added" | "removed") => ({
    value: lines.length ? lines.join("\n") + "\n" : "",
    count: lines.length,
    added: key === "added",
    removed: key === "removed",
  });
  return [asChange(removedLines, "removed"), asChange(addedLines, "added")].filter((c) => c.count);
}
