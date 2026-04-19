<script setup lang="ts">
import { GitBranch, GitFork, WifiOff, XCircle } from "lucide-vue-next";

const {
  messages,
  isStreaming,
  isReconnecting,
  error,
  currentStreamState,
  selectedRepo,
  sendMessage,
  cancelCurrent,
} = useChat();
const { repos } = useRepos();

// Display name for the selected repo
const activeRepoLabel = computed(() => {
  if (!selectedRepo.value) return "";
  const match = repos.value.find(
    (r) => r.repo_full_name === selectedRepo.value,
  );
  return match?.display_name || selectedRepo.value.split("/").pop() || "";
});

const isEmpty = computed(() => messages.value.length === 0);
const hasRepo = computed(() => !!selectedRepo.value);

// Scroll: when the user sends a message, scroll so the user message
// sits near the top. No auto-scroll after that — the user controls
// their own scroll position while the response streams.
const scrollRef = ref<HTMLElement | null>(null);
const prevMessageCount = ref(0);

watch(
  () => messages.value.length,
  (count) => {
    const added = count - prevMessageCount.value;
    prevMessageCount.value = count;

    if (added > 0 && count >= 2) {
      nextTick(() => {
        if (!scrollRef.value) return;

        const msgElements = scrollRef.value.querySelectorAll(
          "[data-chat-message]",
        );
        const userMsgEl = msgElements[msgElements.length - 2] as
          | HTMLElement
          | undefined;
        if (userMsgEl) {
          userMsgEl.scrollIntoView({ behavior: "smooth", block: "start" });
        } else {
          scrollRef.value.scrollTop = scrollRef.value.scrollHeight;
        }
      });
    }
  },
);

function handleSuggestion(question: string) {
  sendMessage(question);
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Active repo indicator -->
    <div
      v-if="selectedRepo"
      class="flex items-center gap-1.5 border-b px-4 h-[37px] shrink-0 text-xs text-muted-foreground"
    >
      <GitBranch class="h-3.5 w-3.5" />
      <span>{{ selectedRepo }}</span>
      <Badge
        v-if="activeRepoLabel !== selectedRepo.split('/').pop()"
        variant="secondary"
        class="text-[10px] ml-1"
      >
        {{ activeRepoLabel }}
      </Badge>
      <div class="ml-auto">
        <ChatExportMenu />
      </div>
    </div>

    <!-- ═══ NO REPO SELECTED — full-page prompt ═══ -->
    <div
      v-if="!hasRepo && isEmpty"
      class="flex-1 flex flex-col items-center justify-center px-4 text-center"
    >
      <div class="rounded-full bg-muted p-4 mb-4">
        <GitFork class="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 class="text-lg font-medium">Repository auswählen</h3>
      <p class="mt-1 text-sm text-muted-foreground max-w-sm">
        Wähle ein Repository in der Seitenleiste aus oder starte einen neuen Chat, um loszulegen.
      </p>
    </div>

    <!-- ═══ REPO SELECTED — normal chat view ═══ -->
    <template v-else>

    <!-- Messages area -->
    <ScrollArea class="flex-1 min-h-0 px-4">
      <div ref="scrollRef" class="mx-auto max-w-3xl space-y-6 py-6">
        <!-- Empty state (repo selected but no messages yet) -->
        <div
          v-if="isEmpty"
          class="flex flex-col items-center justify-center py-20 text-center"
        >
          <div class="rounded-full bg-muted p-4 mb-4">
            <svg
              class="h-8 w-8 text-muted-foreground"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="1.5"
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
          </div>
          <h3 class="text-lg font-medium">GitHub Reporter</h3>
          <p class="mt-1 text-sm text-muted-foreground max-w-sm">
            Stelle Fragen zu deinem Repository – Commits, PRs, Code, Team und mehr.
          </p>

          <SuggestedQuestions class="mt-6" @ask="handleSuggestion" />

          <!-- Input (inline, under bubbles) -->
          <div class="mt-6 w-full max-w-3xl">
            <ChatInput :is-streaming="isStreaming" @send="sendMessage" />
          </div>
        </div>

        <!-- Messages -->
        <ChatMessage
          v-for="(msg, idx) in messages"
          :key="idx"
          :message="msg"
          data-chat-message
        />

        <!-- Reconnecting banner — shown while the stream manager retries -->
        <Alert
          v-if="isReconnecting"
          variant="default"
          class="max-w-3xl mx-auto border-amber-500/40 bg-amber-500/5"
        >
          <WifiOff class="h-4 w-4" />
          <AlertTitle>Verbindung verloren</AlertTitle>
          <AlertDescription>
            Verbindung wird wiederhergestellt
            <span v-if="currentStreamState.reconnectAttempt > 1">
              (Versuch {{ currentStreamState.reconnectAttempt }})
            </span>
            …
          </AlertDescription>
        </Alert>

        <!-- Error -->
        <Alert v-if="error" variant="destructive" class="max-w-3xl mx-auto">
          <AlertTitle>Fehler</AlertTitle>
          <AlertDescription>{{ error }}</AlertDescription>
        </Alert>
      </div>
    </ScrollArea>

    <!-- Cancel in-flight response -->
    <div
      v-if="isStreaming && !isEmpty"
      class="border-t px-4 py-2 flex justify-center"
    >
      <Button
        variant="ghost"
        size="sm"
        class="h-7 gap-1.5 text-xs text-muted-foreground"
        @click="cancelCurrent"
      >
        <XCircle class="h-3.5 w-3.5" />
        Antwort stoppen
      </Button>
    </div>

    <!-- Input (pinned to bottom, only when chatting) -->
    <ChatInput v-if="!isEmpty" :is-streaming="isStreaming" @send="sendMessage" />

    </template>
  </div>
</template>
