<script setup lang="ts">
import {
  AlertCircle,
  ArrowRight,
  Ban,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleDot,
  CirclePlus,
  ExternalLink,
  Eye,
  Loader2,
  Lock,
  MessageSquare,
  Minus,
  Pencil,
  Plus,
  RotateCcw,
  TriangleAlert,
  Undo2,
  XCircle,
} from "lucide-vue-next";
import { formatDate } from "~/composables/useAutomations";
import {
  issueActionErrorMessage,
  issueActionErrorStatus,
} from "~/composables/useIssueActions";
import { computeLineDiff } from "~/utils/lineDiff";
import { refDebounced } from "@vueuse/core";
import {
  ISSUE_BODY_MAX,
  ISSUE_BODY_REPLACE_MAX,
  ISSUE_TITLE_MAX,
  charLength,
  type IssueAction,
  type IssueActionEdits,
  type IssueActionReadOnlyReason,
  type IssueState,
  type IssueStateReason,
} from "~/types/issueActions";

const props = defineProps<{
  actionId: string;
}>();

const { getAction, applyAction, rejectAction } = useIssueActions();
// GitHub renderer: no smart quotes/dashes, so the preview matches what lands
// on GitHub character for character.
const { renderGithub } = useMarkdown();

const action = ref<IssueAction | null>(null);
const loading = ref(true);
const loadError = ref<string | null>(null);
/** Apply/reject failure that isn't already reflected in the draft's state. */
const actionError = ref<string | null>(null);
/** 422 from apply: the server rejected the edited fields; draft unchanged. */
const fieldError = ref<string | null>(null);
const busy = ref<"apply" | "reject" | null>(null);
const editing = ref(false);
/** Terminal states collapse the draft so old cards don't dominate the chat. */
const detailsOpen = ref(false);
/** Update drafts: show the body as a diff or as the rendered new version. */
const bodyView = ref<"diff" | "preview">("diff");

// Local edits — prefilled from the proposal, sent with apply when changed
const editedTitle = ref("");
const editedBody = ref("");

// A server-side field error refers to the values at the time of the attempt;
// once the user types again it no longer applies.
watch([editedTitle, editedBody], () => {
  fieldError.value = null;
});

// ── Loading ────────────────────────────────────────────────────────────

async function load() {
  loading.value = true;
  loadError.value = null;
  try {
    const data = await getAction(props.actionId);
    action.value = data;
    editedTitle.value = data.proposed.title ?? "";
    editedBody.value = data.proposed.body ?? "";
  } catch (e) {
    loadError.value = issueActionErrorMessage(
      e,
      "Der Entwurf konnte nicht geladen werden.",
    );
  } finally {
    loading.value = false;
  }
}

onMounted(load);

// A draft that is "applying" (e.g. confirmed in another tab) resolves within
// seconds — poll until it reaches a terminal state.
let pollTimer: ReturnType<typeof setTimeout> | null = null;
function schedulePoll() {
  pollTimer = setTimeout(async () => {
    try {
      action.value = await getAction(props.actionId);
    } catch {
      // Keep the current state and try again
    }
    if (action.value?.status === "applying") schedulePoll();
  }, 2000);
}
watch(
  () => action.value?.status,
  (status) => {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = null;
    if (status === "applying") schedulePoll();
  },
);
onUnmounted(() => {
  if (pollTimer) clearTimeout(pollTimer);
});

// ── Derived state ──────────────────────────────────────────────────────

const status = computed(() => action.value?.status ?? "pending");
const isPending = computed(() => status.value === "pending");
const isApplying = computed(() => status.value === "applying");
const isTerminal = computed(() =>
  ["applied", "rejected", "failed"].includes(status.value),
);
const canApply = computed(() => isPending.value && !!action.value?.can_apply);

/** Pending, but the last apply attempt hit a fixable problem. */
const retryableError = computed(() =>
  isPending.value ? action.value?.error || null : null,
);

const KIND_META = {
  create_issue: {
    icon: CirclePlus,
    verb: "Issue anlegen",
    busyVerb: "Issue wird angelegt…",
  },
  update_issue: {
    icon: Pencil,
    verb: "Änderungen übernehmen",
    busyVerb: "Änderungen werden übernommen…",
  },
  comment: {
    icon: MessageSquare,
    verb: "Kommentar posten",
    busyVerb: "Kommentar wird gepostet…",
  },
} as const;

const kindMeta = computed(() => KIND_META[action.value?.kind ?? "create_issue"]);

/** What will happen, in plain words. */
const headline = computed(() => {
  const a = action.value;
  if (!a) return "";
  switch (a.kind) {
    case "create_issue":
      return "Neues Issue";
    case "update_issue":
      return `Issue #${a.issue_number} bearbeiten`;
    case "comment":
      return `Kommentar zu Issue #${a.issue_number}`;
  }
});

/** Success line once the draft has been applied. */
const appliedSummary = computed(() => {
  const a = action.value;
  if (!a?.result) return "Auf GitHub übernommen";
  switch (a.kind) {
    case "create_issue":
      return `Issue #${a.result.issue_number} wurde angelegt`;
    case "update_issue":
      return `Issue #${a.result.issue_number} wurde aktualisiert`;
    case "comment":
      return `Kommentar zu Issue #${a.result.issue_number} wurde gepostet`;
  }
});

const githubUrl = computed(() => {
  const r = action.value?.result;
  if (!r) return null;
  return action.value?.kind === "comment" && r.comment_url
    ? r.comment_url
    : r.html_url;
});

const READ_ONLY_COPY: Record<IssueActionReadOnlyReason, string> = {
  viewer: "Nur Lesezugriff – Änderungen kann nur ein GitHub-Nutzer übernehmen.",
  suspended:
    "Dein Konto ist gesperrt – Änderungen können nicht übernommen werden.",
};
const readOnlyText = computed(
  () => READ_ONLY_COPY[action.value?.read_only_reason ?? "viewer"],
);

// Which fields the user may edit: for update only the ones the agent touched,
// so a user edit never silently overwrites something the agent left alone.
const titleEditable = computed(() => {
  const a = action.value;
  if (!a) return false;
  if (a.kind === "create_issue") return true;
  return a.kind === "update_issue" && a.proposed.title !== undefined;
});
const bodyEditable = computed(() => {
  const a = action.value;
  if (!a) return false;
  if (a.kind === "update_issue") {
    // Long bodies can't be replaced (the agent only saw part of them), so an
    // edit could never be saved — the draft can still be applied unchanged.
    return a.proposed.body !== undefined && charLength(a.current?.body ?? "") <= ISSUE_BODY_REPLACE_MAX;
  }
  return true;
});
const canEdit = computed(
  () => canApply.value && (titleEditable.value || bodyEditable.value),
);

const isDirty = computed(() => {
  const p = action.value?.proposed;
  if (!p) return false;
  return (
    editedTitle.value !== (p.title ?? "") || editedBody.value !== (p.body ?? "")
  );
});

// ── Limits ─────────────────────────────────────────────────────────────

const bodyNoun = computed(() =>
  action.value?.kind === "comment" ? "Der Kommentar" : "Die Beschreibung",
);

const titleOver = computed(
  () => titleEditable.value && charLength(editedTitle.value) > ISSUE_TITLE_MAX,
);
const bodyOver = computed(
  () => bodyEditable.value && charLength(editedBody.value) > ISSUE_BODY_MAX,
);

const fmt = (n: number) => n.toLocaleString("de-DE");

/** "n / max" once the field is near or over its limit; otherwise nothing. */
function counter(length: number, max: number): string | null {
  return length >= max * 0.9 ? `${fmt(length)} / ${fmt(max)}` : null;
}
const titleCounter = computed(() => counter(charLength(editedTitle.value), ISSUE_TITLE_MAX));
const bodyCounter = computed(() => counter(charLength(editedBody.value), ISSUE_BODY_MAX));

const validationError = computed(() => {
  if (!canApply.value) return null;
  if (titleEditable.value && !editedTitle.value.trim()) {
    return "Der Titel darf nicht leer sein.";
  }
  if (titleOver.value) {
    return `Der Titel darf höchstens ${fmt(ISSUE_TITLE_MAX)} Zeichen lang sein (aktuell ${fmt(charLength(editedTitle.value))}).`;
  }
  if (action.value?.kind === "comment" && !editedBody.value.trim()) {
    return "Der Kommentar darf nicht leer sein.";
  }
  if (bodyOver.value) {
    return `${bodyNoun.value} darf höchstens ${fmt(ISSUE_BODY_MAX)} Zeichen lang sein (aktuell ${fmt(charLength(editedBody.value))}).`;
  }
  return null;
});

const renderedBody = computed(() => renderGithub(editedBody.value));

// ── Update diff — only the fields that actually change ─────────────────

function diffList(before: string[], after: string[]) {
  const added = after.filter((x) => !before.includes(x));
  const removed = before.filter((x) => !after.includes(x));
  return added.length || removed.length ? { added, removed } : null;
}

const changes = computed(() => {
  const a = action.value;
  if (!a || a.kind !== "update_issue" || !a.current) return null;
  const p = a.proposed;
  const c = a.current;
  return {
    title: p.title !== undefined && p.title !== c.title,
    state:
      p.state !== undefined && p.state !== c.state
        ? { from: c.state, to: p.state, reason: p.state_reason }
        : null,
    labels: p.labels ? diffList(c.labels, p.labels) : null,
    assignees: p.assignees ? diffList(c.assignees, p.assignees) : null,
    body: p.body !== undefined && p.body !== c.body,
  };
});

const hasChanges = computed(() => {
  const ch = changes.value;
  return (
    !!ch && (ch.title || !!ch.state || !!ch.labels || !!ch.assignees || ch.body)
  );
});

// Line diff of the body as it will be written (including the user's edits)
// against the issue as it is now — the only way a large deletion is visible.
// Debounced while editing: recomputing the diff per keystroke on long bodies
// stalls the page. Outside edit mode the text is stable, so use it directly
// (the debounced copy would briefly lag behind the initial load).
const debouncedBody = refDebounced(editedBody, 300);
const bodyDiff = computed(() => {
  const a = action.value;
  if (!a || !changes.value?.body || !a.current) return null;
  return computeLineDiff(a.current.body, editing.value ? debouncedBody.value : editedBody.value);
});

const diffSummary = computed(() => {
  const d = bodyDiff.value;
  if (!d || d.identical) return null;
  return `+${fmt(d.added)} / −${fmt(d.removed)} Zeilen`;
});

const STATE_LABELS: Record<IssueState, string> = {
  open: "Offen",
  closed: "Geschlossen",
};
const STATE_REASON_LABELS: Record<IssueStateReason, string> = {
  completed: "Erledigt",
  not_planned: "Nicht geplant",
  reopened: "Wiedereröffnet",
};

// ── Status pill ────────────────────────────────────────────────────────

const statusPill = computed(() => {
  switch (status.value) {
    case "applied":
      return { label: "Übernommen", icon: CheckCircle2, classes: "border-emerald-500/40 text-emerald-600 dark:text-emerald-400" };
    case "rejected":
      return { label: "Verworfen", icon: Ban, classes: "text-muted-foreground" };
    case "failed":
      return { label: "Fehlgeschlagen", icon: XCircle, classes: "border-destructive/40 text-destructive" };
    case "applying":
      return { label: "Wird übernommen", icon: Loader2, classes: "text-muted-foreground", spin: true };
    default:
      if (action.value?.can_apply) {
        return { label: "Wartet auf Bestätigung", icon: null, classes: "border-amber-500/40 text-amber-600 dark:text-amber-400" };
      }
      return action.value?.read_only_reason === "suspended"
        ? { label: "Konto gesperrt", icon: Lock, classes: "text-muted-foreground" }
        : { label: "Nur Lesezugriff", icon: Lock, classes: "text-muted-foreground" };
  }
});

const headerIconClass = computed(() => {
  switch (status.value) {
    case "applied":
      return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
    case "failed":
      return "bg-destructive/10 text-destructive";
    case "rejected":
      return "bg-muted text-muted-foreground";
    default:
      return "bg-primary/10 text-primary";
  }
});

// ── Actions ────────────────────────────────────────────────────────────

const titleInput = ref<{ $el?: HTMLInputElement } | null>(null);
const bodyInput = ref<{ $el?: HTMLTextAreaElement } | null>(null);

function toggleEditing() {
  editing.value = !editing.value;
  if (editing.value) {
    nextTick(() => {
      (titleEditable.value ? titleInput.value : bodyInput.value)?.$el?.focus();
    });
  }
}

function resetEdits() {
  const p = action.value?.proposed;
  editedTitle.value = p?.title ?? "";
  editedBody.value = p?.body ?? "";
}

/**
 * Shared tail of apply/reject. A 422 means our edits were refused and the
 * draft is untouched — show it at the fields. Anything else may have changed
 * the stored draft (resolved elsewhere, GitHub refused, …), so re-sync and
 * only add a message when the refreshed state doesn't explain itself.
 */
async function handleActionError(e: unknown, fallback: string) {
  if (issueActionErrorStatus(e) === 422) {
    fieldError.value = issueActionErrorMessage(e, fallback);
    if (canEdit.value) {
      editing.value = true;
      nextTick(() => bodyInput.value?.$el?.scrollIntoView?.({ block: "nearest" }));
    }
    return;
  }
  try {
    action.value = await getAction(props.actionId);
    if (action.value.status === "pending" && !action.value.error) {
      actionError.value = issueActionErrorMessage(e, fallback);
    }
    return;
  } catch {
    // Fall through to the generic message
  }
  actionError.value = issueActionErrorMessage(e, fallback);
}

async function confirm() {
  if (busy.value || !canApply.value || validationError.value) return;
  busy.value = "apply";
  actionError.value = null;
  fieldError.value = null;
  try {
    const edits: IssueActionEdits = {};
    const p = action.value!.proposed;
    if (titleEditable.value && editedTitle.value !== (p.title ?? "")) {
      edits.title = editedTitle.value.trim();
    }
    if (bodyEditable.value && editedBody.value !== (p.body ?? "")) {
      edits.body = editedBody.value;
    }
    action.value = await applyAction(props.actionId, edits);
    editing.value = false;
  } catch (e) {
    await handleActionError(e, "Der Entwurf konnte nicht übernommen werden.");
  } finally {
    busy.value = null;
  }
}

async function discard() {
  if (busy.value || !isPending.value) return;
  busy.value = "reject";
  actionError.value = null;
  try {
    action.value = await rejectAction(props.actionId);
    editing.value = false;
  } catch (e) {
    await handleActionError(e, "Der Entwurf konnte nicht verworfen werden.");
  } finally {
    busy.value = null;
  }
}

const fieldLabelClass =
  "text-[11px] font-medium uppercase tracking-wide text-muted-foreground";
const counterClass = (over: boolean) =>
  over
    ? "text-[11px] tabular-nums text-destructive"
    : "text-[11px] tabular-nums text-muted-foreground";
const segmentClass = (active: boolean) =>
  active
    ? "rounded-sm bg-background px-2 py-0.5 text-xs font-medium shadow-sm"
    : "rounded-sm px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground";
</script>

<template>
  <!-- Loading skeleton -->
  <Card v-if="loading" class="gap-0 rounded-lg py-0 shadow-sm">
    <div class="flex items-center gap-3 px-4 py-3">
      <Skeleton class="h-8 w-8 shrink-0 rounded-md" />
      <div class="flex-1 space-y-1.5">
        <Skeleton class="h-3.5 w-40 max-w-full" />
        <Skeleton class="h-3 w-24" />
      </div>
    </div>
    <div class="space-y-2 border-t px-4 py-3">
      <Skeleton class="h-3 w-full" />
      <Skeleton class="h-3 w-3/4" />
    </div>
  </Card>

  <!-- Load error -->
  <Card
    v-else-if="loadError || !action"
    class="gap-0 rounded-lg py-0 shadow-sm"
  >
    <div class="flex flex-wrap items-start gap-3 px-4 py-3 text-sm">
      <AlertCircle class="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
      <div class="min-w-0 flex-1">
        <p class="font-medium">Entwurf konnte nicht geladen werden</p>
        <p class="text-muted-foreground">{{ loadError }}</p>
      </div>
      <Button variant="outline" size="sm" class="h-7 text-xs" @click="load">
        <RotateCcw class="h-3.5 w-3.5" />
        Erneut laden
      </Button>
    </div>
  </Card>

  <!-- Draft card -->
  <Card
    v-else
    class="gap-0 rounded-lg py-0 shadow-sm transition-opacity"
    :class="status === 'rejected' ? 'opacity-70' : ''"
    :aria-busy="!!busy || isApplying"
  >
    <!-- Header: what will happen, where -->
    <div class="flex items-start gap-3 px-4 py-3">
      <div
        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md"
        :class="headerIconClass"
      >
        <component :is="kindMeta.icon" class="h-4 w-4" />
      </div>
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span class="text-sm font-medium leading-tight">{{ headline }}</span>
          <Badge
            variant="outline"
            class="ml-auto px-1.5 py-0 text-[10px]"
            :class="statusPill.classes"
          >
            <component
              :is="statusPill.icon"
              v-if="statusPill.icon"
              :class="statusPill.spin ? 'animate-spin' : ''"
            />
            {{ statusPill.label }}
          </Badge>
        </div>
        <p
          class="mt-0.5 line-clamp-2 text-xs text-muted-foreground [overflow-wrap:anywhere]"
        >
          <span>{{ action.repo }}</span>
          <template v-if="action.current">
            <span class="ml-1">·</span>{{ " " }}<a
              :href="action.current.html_url"
              target="_blank"
              rel="noopener"
              class="hover:text-foreground hover:underline underline-offset-2"
              >{{ action.current.title }}</a
            >
          </template>
        </p>
      </div>
    </div>

    <!-- Draft details (collapsed in terminal states) -->
    <div
      v-if="!isTerminal || detailsOpen"
      class="space-y-4 border-t px-4 py-3"
    >
      <!-- ── create_issue ── -->
      <template v-if="action.kind === 'create_issue'">
        <div class="space-y-1.5">
          <Label v-if="editing" :for="`${actionId}-title`" :class="fieldLabelClass">Titel</Label>
          <p v-else :class="fieldLabelClass">Titel</p>
          <template v-if="editing">
            <Input
              :id="`${actionId}-title`"
              ref="titleInput"
              v-model="editedTitle"
              :disabled="!!busy"
              :aria-invalid="titleOver || undefined"
              class="h-8 text-sm"
            />
            <p v-if="titleCounter" class="text-right" :class="counterClass(titleOver)">
              {{ titleCounter }}
            </p>
          </template>
          <p
            v-else
            class="text-sm font-medium leading-snug break-words [overflow-wrap:anywhere]"
          >
            {{ editedTitle || "—" }}
          </p>
        </div>

        <div
          v-if="action.proposed.labels?.length || action.proposed.assignees?.length"
          class="flex flex-wrap gap-x-6 gap-y-3"
        >
          <div v-if="action.proposed.labels?.length" class="space-y-1.5">
            <p :class="fieldLabelClass">Labels</p>
            <div class="flex flex-wrap gap-1">
              <Badge
                v-for="label in action.proposed.labels"
                :key="label"
                variant="secondary"
                class="text-[11px]"
              >
                {{ label }}
              </Badge>
            </div>
          </div>
          <div v-if="action.proposed.assignees?.length" class="space-y-1.5">
            <p :class="fieldLabelClass">Zuständig</p>
            <div class="flex flex-wrap gap-1">
              <Badge
                v-for="user in action.proposed.assignees"
                :key="user"
                variant="outline"
                class="text-[11px] font-normal"
              >
                @{{ user }}
              </Badge>
            </div>
          </div>
        </div>

        <div class="space-y-1.5">
          <Label v-if="editing" :for="`${actionId}-body`" :class="fieldLabelClass">Beschreibung</Label>
          <p v-else :class="fieldLabelClass">Beschreibung</p>
          <template v-if="editing">
            <Textarea
              :id="`${actionId}-body`"
              ref="bodyInput"
              v-model="editedBody"
              :disabled="!!busy"
              :aria-invalid="bodyOver || undefined"
              class="max-h-[60vh] min-h-32 text-sm"
            />
            <p v-if="bodyCounter" class="text-right" :class="counterClass(bodyOver)">
              {{ bodyCounter }}
            </p>
          </template>
          <ExpandableBlock v-else-if="editedBody.trim()">
            <div
              class="markdown markdown-compact text-foreground/90"
              v-html="renderedBody"
            />
          </ExpandableBlock>
          <p v-else class="text-sm italic text-muted-foreground">
            Keine Beschreibung
          </p>
        </div>
      </template>

      <!-- ── update_issue: before → after, changed fields only ── -->
      <template v-else-if="action.kind === 'update_issue'">
        <p v-if="!hasChanges" class="text-sm text-muted-foreground">
          Keine Änderungen gegenüber dem aktuellen Stand.
        </p>

        <div v-if="changes?.title" class="space-y-1.5">
          <Label v-if="editing" :for="`${actionId}-title`" :class="fieldLabelClass">Titel</Label>
          <p v-else :class="fieldLabelClass">Titel</p>
          <p
            class="text-sm text-muted-foreground line-through decoration-muted-foreground/50 break-words [overflow-wrap:anywhere]"
          >
            {{ action.current?.title }}
          </p>
          <template v-if="editing">
            <Input
              :id="`${actionId}-title`"
              ref="titleInput"
              v-model="editedTitle"
              :disabled="!!busy"
              :aria-invalid="titleOver || undefined"
              class="h-8 text-sm"
            />
            <p v-if="titleCounter" class="text-right" :class="counterClass(titleOver)">
              {{ titleCounter }}
            </p>
          </template>
          <p
            v-else
            class="text-sm font-medium leading-snug break-words [overflow-wrap:anywhere]"
          >
            {{ editedTitle || "—" }}
          </p>
        </div>

        <div v-if="changes?.state" class="space-y-1.5">
          <p :class="fieldLabelClass">Status</p>
          <div class="flex flex-wrap items-center gap-1.5 text-sm">
            <span class="inline-flex items-center gap-1 text-muted-foreground">
              <component
                :is="changes.state.from === 'open' ? CircleDot : CircleCheck"
                class="h-3.5 w-3.5"
              />
              {{ STATE_LABELS[changes.state.from] }}
            </span>
            <ArrowRight class="h-3.5 w-3.5 text-muted-foreground" />
            <span class="inline-flex items-center gap-1 font-medium">
              <component
                :is="changes.state.to === 'open' ? CircleDot : CircleCheck"
                class="h-3.5 w-3.5"
                :class="changes.state.to === 'open' ? 'text-emerald-600 dark:text-emerald-400' : 'text-purple-600 dark:text-purple-400'"
              />
              {{ STATE_LABELS[changes.state.to] }}
            </span>
            <span v-if="changes.state.reason" class="text-muted-foreground">
              · {{ STATE_REASON_LABELS[changes.state.reason] }}
            </span>
          </div>
        </div>

        <div
          v-if="changes?.labels || changes?.assignees"
          class="flex flex-wrap gap-x-6 gap-y-3"
        >
          <div v-if="changes?.labels" class="space-y-1.5">
            <p :class="fieldLabelClass">Labels</p>
            <div class="flex flex-wrap gap-1">
              <Badge
                v-for="label in changes.labels.added"
                :key="`+${label}`"
                variant="outline"
                class="border-emerald-500/40 text-[11px] text-emerald-700 dark:text-emerald-400"
              >
                <Plus />
                {{ label }}
              </Badge>
              <Badge
                v-for="label in changes.labels.removed"
                :key="`-${label}`"
                variant="outline"
                class="text-[11px] text-muted-foreground line-through"
              >
                <Minus />
                {{ label }}
              </Badge>
            </div>
          </div>
          <div v-if="changes?.assignees" class="space-y-1.5">
            <p :class="fieldLabelClass">Zuständig</p>
            <div class="flex flex-wrap gap-1">
              <Badge
                v-for="user in changes.assignees.added"
                :key="`+${user}`"
                variant="outline"
                class="border-emerald-500/40 text-[11px] font-normal text-emerald-700 dark:text-emerald-400"
              >
                <Plus />
                @{{ user }}
              </Badge>
              <Badge
                v-for="user in changes.assignees.removed"
                :key="`-${user}`"
                variant="outline"
                class="text-[11px] font-normal text-muted-foreground line-through"
              >
                <Minus />
                @{{ user }}
              </Badge>
            </div>
          </div>
        </div>

        <!-- Body: diff against the issue as it is now, or the rendered new version -->
        <div v-if="changes?.body && bodyDiff" class="space-y-2">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <Label v-if="editing" :for="`${actionId}-body`" :class="fieldLabelClass">Neue Beschreibung</Label>
            <p v-else :class="fieldLabelClass">Beschreibung</p>
            <span
              v-if="diffSummary"
              class="rounded-full border px-1.5 py-px font-mono text-[10px] tabular-nums text-muted-foreground"
            >
              {{ diffSummary }}
            </span>
            <div
              v-if="!editing && !bodyDiff.identical"
              class="ml-auto inline-flex rounded-md bg-muted p-0.5"
              role="group"
              aria-label="Ansicht der Beschreibung"
            >
              <button
                type="button"
                :class="segmentClass(bodyView === 'diff')"
                :aria-pressed="bodyView === 'diff'"
                @click="bodyView = 'diff'"
              >
                Änderungen
              </button>
              <button
                type="button"
                :class="segmentClass(bodyView === 'preview')"
                :aria-pressed="bodyView === 'preview'"
                @click="bodyView = 'preview'"
              >
                Neue Fassung
              </button>
            </div>
          </div>

          <!-- Large deletion: must be impossible to miss before confirming -->
          <div
            v-if="bodyDiff.destructive"
            role="alert"
            class="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-200"
          >
            <TriangleAlert class="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <p>
              <span class="font-medium">Achtung:</span> Diese Änderung entfernt einen
              großen Teil der bisherigen Beschreibung
              <span class="whitespace-nowrap">({{ fmt(bodyDiff.removed) }} von {{ fmt(bodyDiff.oldLines) }} Zeilen).</span>
            </p>
          </div>

          <template v-if="editing">
            <Textarea
              :id="`${actionId}-body`"
              ref="bodyInput"
              v-model="editedBody"
              :disabled="!!busy"
              :aria-invalid="bodyOver || undefined"
              class="max-h-[60vh] min-h-32 text-sm"
            />
            <p v-if="bodyCounter" class="text-right" :class="counterClass(bodyOver)">
              {{ bodyCounter }}
            </p>
          </template>
          <p v-else-if="bodyDiff.identical" class="text-sm italic text-muted-foreground">
            Beschreibung bleibt unverändert
          </p>
          <LineDiffView v-else-if="bodyView === 'diff'" :diff="bodyDiff" />
          <ExpandableBlock v-else-if="editedBody.trim()">
            <div
              class="markdown markdown-compact text-foreground/90"
              v-html="renderedBody"
            />
          </ExpandableBlock>
          <p v-else class="text-sm italic text-muted-foreground">
            Beschreibung wird geleert
          </p>
        </div>
      </template>

      <!-- ── comment ── -->
      <template v-else>
        <div class="space-y-1.5">
          <Label v-if="editing" :for="`${actionId}-body`" :class="fieldLabelClass">Kommentar</Label>
          <p v-else :class="fieldLabelClass">Kommentar</p>
          <template v-if="editing">
            <Textarea
              :id="`${actionId}-body`"
              ref="bodyInput"
              v-model="editedBody"
              :disabled="!!busy"
              :aria-invalid="bodyOver || undefined"
              class="max-h-[60vh] min-h-32 text-sm"
            />
            <p v-if="bodyCounter" class="text-right" :class="counterClass(bodyOver)">
              {{ bodyCounter }}
            </p>
          </template>
          <ExpandableBlock v-else>
            <div
              class="border-l-2 pl-3 markdown markdown-compact text-foreground/90"
              v-html="renderedBody"
            />
          </ExpandableBlock>
        </div>
      </template>

      <p v-if="editing && bodyEditable" class="text-xs text-muted-foreground">
        Markdown wird unterstützt.
      </p>
      <p v-if="validationError" class="text-xs text-destructive">
        {{ validationError }}
      </p>
      <!-- Server refused the edited values; the draft itself is unchanged -->
      <div
        v-if="fieldError"
        role="alert"
        class="flex items-start gap-2 text-xs text-destructive"
      >
        <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <p>{{ fieldError }}</p>
      </div>
    </div>

    <!-- Failure: the error, plus how to move on -->
    <div v-if="status === 'failed'" class="border-t px-4 py-3">
      <Alert variant="destructive" class="border-destructive/30 px-3 py-2.5">
        <XCircle class="h-4 w-4" />
        <AlertTitle class="text-sm">Nicht übernommen</AlertTitle>
        <AlertDescription class="text-xs">
          <p>{{ action.error || "Beim Schreiben auf GitHub ist ein Fehler aufgetreten." }}</p>
          <p class="text-muted-foreground">
            Du kannst den Assistenten um einen neuen Entwurf bitten.
          </p>
        </AlertDescription>
      </Alert>
    </div>

    <!-- Applied, but GitHub quietly dropped part of it -->
    <div
      v-if="status === 'applied' && action.result?.warning"
      class="border-t px-4 py-3"
    >
      <div
        class="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-900 dark:text-amber-200"
      >
        <TriangleAlert class="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
        <p>{{ action.result.warning }}</p>
      </div>
    </div>

    <!-- Pending, but the last attempt failed for a fixable reason -->
    <div v-if="retryableError" class="border-t px-4 py-3">
      <Alert class="border-amber-500/40 bg-amber-500/5 px-3 py-2.5 text-amber-900 dark:text-amber-200">
        <TriangleAlert class="h-4 w-4 text-amber-600 dark:text-amber-400" />
        <AlertTitle class="text-sm">Letzter Versuch fehlgeschlagen</AlertTitle>
        <AlertDescription class="text-xs text-amber-900/80 dark:text-amber-200/80">
          <p>{{ retryableError }}</p>
          <p v-if="canApply">
            Der Entwurf bleibt erhalten – sobald das Problem behoben ist, kannst du
            es erneut versuchen.
          </p>
        </AlertDescription>
      </Alert>
    </div>

    <!-- Apply/reject error that didn't change the draft's state -->
    <div v-if="actionError" class="border-t px-4 py-3">
      <Alert variant="destructive" class="border-destructive/30 px-3 py-2.5">
        <AlertCircle class="h-4 w-4" />
        <AlertDescription class="text-xs">{{ actionError }}</AlertDescription>
      </Alert>
    </div>

    <!-- Footer -->
    <div class="border-t px-4 py-3">
      <!-- Pending, user may confirm -->
      <div
        v-if="canApply"
        class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
      >
        <p class="text-xs text-muted-foreground">
          Noch nichts auf GitHub geändert.
          <button
            v-if="isDirty && !busy"
            type="button"
            class="ml-1 inline-flex items-center gap-1 underline underline-offset-2 hover:text-foreground"
            @click="resetEdits"
          >
            <Undo2 class="h-3 w-3" />
            Änderungen zurücksetzen
          </button>
        </p>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
          <div class="flex gap-2">
            <Button
              variant="ghost"
              size="sm"
              class="h-8 flex-1 text-muted-foreground sm:flex-none"
              :disabled="!!busy"
              @click="discard"
            >
              <Loader2 v-if="busy === 'reject'" class="animate-spin" />
              Verwerfen
            </Button>
            <Button
              v-if="canEdit"
              variant="outline"
              size="sm"
              class="h-8 flex-1 sm:flex-none"
              :disabled="!!busy"
              @click="toggleEditing"
            >
              <component :is="editing ? Eye : Pencil" />
              {{ editing ? "Vorschau" : "Bearbeiten" }}
            </Button>
          </div>
          <Button
            size="sm"
            class="h-8"
            :disabled="!!busy || !!validationError"
            @click="confirm"
          >
            <Loader2 v-if="busy === 'apply'" class="animate-spin" />
            <RotateCcw v-else-if="retryableError" />
            {{ busy === "apply" ? kindMeta.busyVerb : kindMeta.verb }}
          </Button>
        </div>
      </div>

      <!-- Pending, but this account can't write -->
      <div
        v-else-if="isPending"
        class="flex items-start gap-2 text-xs text-muted-foreground"
      >
        <Lock class="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{{ readOnlyText }}</span>
      </div>

      <!-- Being applied right now (e.g. confirmed in another tab) -->
      <div
        v-else-if="isApplying"
        class="flex items-center gap-2 text-xs text-muted-foreground"
      >
        <Loader2 class="h-3.5 w-3.5 animate-spin" />
        <span>Wird gerade auf GitHub übernommen…</span>
      </div>

      <!-- Terminal states -->
      <div
        v-else
        class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
      >
        <div class="min-w-0 text-xs text-muted-foreground">
          <template v-if="status === 'applied'">
            <span class="text-foreground">{{ appliedSummary }}</span>
            <span class="mx-1">·</span>
            <span>{{ formatDate(action.updated_at) }}</span>
          </template>
          <template v-else-if="status === 'rejected'">
            Verworfen am {{ formatDate(action.updated_at) }}
          </template>
          <template v-else>
            Fehlgeschlagen am {{ formatDate(action.updated_at) }}
          </template>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            class="h-7 text-xs text-muted-foreground"
            @click="detailsOpen = !detailsOpen"
          >
            <component :is="detailsOpen ? ChevronDown : ChevronRight" class="h-3.5 w-3.5" />
            {{ detailsOpen ? "Details ausblenden" : "Details anzeigen" }}
          </Button>
          <Button
            v-if="status === 'applied' && githubUrl"
            variant="outline"
            size="sm"
            class="h-7 text-xs"
            as-child
          >
            <a :href="githubUrl" target="_blank" rel="noopener">
              <ExternalLink class="h-3.5 w-3.5" />
              Auf GitHub öffnen
            </a>
          </Button>
        </div>
      </div>
    </div>
  </Card>
</template>
