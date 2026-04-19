<script setup lang="ts">
/**
 * Chat route — handles both `/chat` (new chat) and `/chat/:chatId`.
 *
 * URL is the source of truth for which chat is active:
 *   - URL → state: on mount & on param change, hydrate via loadChat(id) or newChat()
 *   - state → URL: when sendMessage mints a fresh chat id, reflect it in the URL
 *   - bad id (404) → redirect back to /chat
 */
const route = useRoute();
const router = useRouter();
const { activeChatId, loadChat, newChat } = useChat();

const routeChatId = computed(
  () => (route.params.chatId as string | undefined) || null,
);

async function syncFromUrl(id: string | null) {
  if (id === activeChatId.value) return;
  if (id) {
    try {
      await loadChat(id);
    } catch {
      // Unknown/forbidden chat id — drop it from the URL and show an empty chat.
      await router.replace("/chat");
    }
  } else {
    newChat();
  }
}

// Hydrate on first mount (client-side — apiFetch relies on cookies).
onMounted(() => {
  syncFromUrl(routeChatId.value);
});

// React to URL changes (sidebar navigation, browser back/forward, manual edits).
watch(routeChatId, (id) => {
  syncFromUrl(id);
});

// Reflect state changes back to the URL — specifically, sendMessage() mints a
// new chat id on the first send, which we want to land in the address bar.
watch(activeChatId, (id) => {
  if (id === routeChatId.value) return;
  router.replace(id ? `/chat/${id}` : "/chat");
});
</script>

<template>
  <main class="flex h-[calc(100vh-3.5rem)]">
    <!-- Chat history sidebar (desktop) -->
    <aside class="hidden md:flex w-64 border-r flex-col shrink-0">
      <ChatHistory />
    </aside>

    <!-- Main chat area -->
    <div class="flex-1 min-w-0">
      <ChatInterface />
    </div>
  </main>
</template>
