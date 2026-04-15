<script setup lang="ts">
import { Download, FileText, FileDown } from "lucide-vue-next";

const { messages, selectedRepo, activeChatId, chatList } = useChat();
const { exportMarkdown, exportPdf } = useChatExport();

const hasMessages = computed(() => messages.value.length > 0);

/** Resolve the current chat title from the chat list (or fall back). */
const chatTitle = computed(() => {
  if (!activeChatId.value) return undefined;
  const match = chatList.value.find((c) => c.chat_id === activeChatId.value);
  return match?.title;
});

const meta = computed(() => ({
  repo: selectedRepo.value || undefined,
  title: chatTitle.value,
}));

function handleMarkdown() {
  exportMarkdown(messages.value, meta.value);
}

function handlePdf() {
  exportPdf(messages.value, meta.value);
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button
        variant="ghost"
        size="icon"
        class="h-8 w-8"
        :disabled="!hasMessages"
        title="Chat exportieren"
      >
        <Download class="h-4 w-4" />
      </Button>
    </DropdownMenuTrigger>

    <DropdownMenuContent align="end" class="w-48">
      <DropdownMenuLabel>Chat exportieren</DropdownMenuLabel>
      <DropdownMenuSeparator />

      <DropdownMenuItem class="gap-2 cursor-pointer" @click="handleMarkdown">
        <FileText class="h-4 w-4" />
        <span>Markdown (.md)</span>
      </DropdownMenuItem>

      <DropdownMenuItem class="gap-2 cursor-pointer" @click="handlePdf">
        <FileDown class="h-4 w-4" />
        <span>PDF exportieren</span>
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
