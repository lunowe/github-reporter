<script setup lang="ts">
import { User, Bot, ChevronDown, ChevronRight, Loader2 } from "lucide-vue-next";
import type { ChatMessage } from "~/types/chat";

const { render: renderMarkdown } = useMarkdown();

const props = defineProps<{
  message: ChatMessage;
}>();

const isUser = computed(() => props.message.role === "user");

const renderedContent = computed(() => {
  if (isUser.value || !props.message.content) return "";
  return renderMarkdown(props.message.content);
});

// Track which tool calls are expanded
const expandedTools = ref<Set<number>>(new Set());
function toggleTool(index: number) {
  if (expandedTools.value.has(index)) {
    expandedTools.value.delete(index);
  } else {
    expandedTools.value.add(index);
  }
}

const TOOL_LABELS: Record<string, string> = {
  get_commits: "Commits abrufen",
  list_pull_requests: "Pull Requests auflisten",
  get_pr_detail: "PR-Details abrufen",
  list_issues: "Issues auflisten",
  get_issue_detail: "Issue-Details abrufen",
  get_workflow_runs: "CI/CD Status prüfen",
  get_repo_summary: "Repository-Übersicht laden",
  browse_directory: "Verzeichnis durchsuchen",
  read_file: "Datei lesen",
  compare_branches: "Branches vergleichen",
  get_contributors: "Contributors abrufen",
  search_code: "Code durchsuchen",
};

// True when the assistant message is still empty (waiting for first token or tool call)
const isThinking = computed(
  () => !isUser.value && !props.message.content && !props.message.toolCalls?.length,
);

// True when all tool calls are done but the assistant hasn't started responding with text yet
const isThinkingAfterTools = computed(() => {
  if (isUser.value || props.message.content) return false;
  const calls = props.message.toolCalls;
  if (!calls?.length) return false;
  return calls.every((tc) => tc.status === "done" || tc.status === "error");
});
</script>

<template>
  <div class="flex gap-3" :class="isUser ? 'justify-end' : ''">
    <!-- Avatar -->
    <!-- <Avatar v-if="!isUser" class="h-8 w-8 shrink-0">
      <AvatarFallback class="bg-primary text-primary-foreground text-xs">
        <Bot class="h-4 w-4" />
      </AvatarFallback>
    </Avatar> -->

    <div class="max-w-[85%] space-y-2" :class="isUser ? 'order-first' : ''">
      <!-- Thinking indicator -->
      <div
        v-if="isThinking"
        class="flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm text-muted-foreground"
      >
        <Loader2 class="h-4 w-4 animate-spin" />
        <span>Denkt nach...</span>
      </div>

      <!-- Tool calls -->
      <div v-if="!isUser && message.toolCalls?.length" class="space-y-1">
        <div
          v-for="(tc, idx) in message.toolCalls"
          :key="idx"
          class="rounded-md border bg-muted/50 text-xs"
        >
          <button
            class="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-muted/80"
            @click="toggleTool(idx)"
          >
            <Loader2
              v-if="tc.status === 'running'"
              class="h-3 w-3 animate-spin text-muted-foreground"
            />
            <component
              :is="expandedTools.has(idx) ? ChevronDown : ChevronRight"
              v-else
              class="h-3 w-3 text-muted-foreground"
            />
            <span class="font-medium">
              {{ TOOL_LABELS[tc.name] || tc.name }}
            </span>
            <Badge
              v-if="tc.status === 'done'"
              variant="secondary"
              class="ml-auto text-[10px] px-1.5 py-0"
            >
              fertig
            </Badge>
          </button>

          <Collapsible :open="expandedTools.has(idx)">
            <CollapsibleContent>
              <div class="border-t px-3 py-2">
                <pre
                  v-if="tc.output"
                  class="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] text-muted-foreground"
                  >{{ tc.output }}</pre
                >
                <span v-else class="text-muted-foreground">Läuft...</span>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      </div>

      <!-- Thinking indicator after tool calls complete -->
      <div
        v-if="isThinkingAfterTools"
        class="flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm text-muted-foreground"
      >
        <Loader2 class="h-4 w-4 animate-spin" />
        <span>Denkt nach...</span>
      </div>

      <!-- User message (plain text) -->
      <div
        v-if="isUser && message.content"
        class="rounded-lg px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap bg-muted text-foreground"
      >
        {{ message.content }}
      </div>

      <!-- Assistant message (markdown) -->
      <div
        v-else-if="!isUser && message.content"
        class="rounded-lg px-4 py-2.5 markdown text-foreground/90"
        v-html="renderedContent"
      />
    </div>

    <!-- User avatar -->
    <!-- <Avatar v-if="isUser" class="h-8 w-8 shrink-0">
      <AvatarFallback class="bg-secondary text-xs">
        <User class="h-4 w-4" />
      </AvatarFallback>
    </Avatar> -->
  </div>
</template>
