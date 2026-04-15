<script setup lang="ts">
import {
  MessageSquarePlus,
  Trash2,
  Loader2,
  ChevronRight,
  Plus,
  Settings,
  FolderGit2,
} from "lucide-vue-next";

const {
  chatList,
  chatListLoading,
  activeChatId,
  selectedRepo,
  fetchChatList,
  loadChat,
  newChat,
  deleteChat,
} = useChat();

const { repos, fetchRepos } = useRepos();

const INITIAL_VISIBLE_COUNT = 5;
const expandedGroups = ref<Set<string>>(new Set());

function isGroupExpanded(repo: string) {
  return expandedGroups.value.has(repo);
}

function toggleShowMore(repo: string) {
  if (expandedGroups.value.has(repo)) {
    expandedGroups.value.delete(repo);
  } else {
    expandedGroups.value.add(repo);
  }
}

function visibleChats(group: { repo: string; chats: typeof chatList.value }) {
  if (isGroupExpanded(group.repo) || group.chats.length <= INITIAL_VISIBLE_COUNT) {
    return group.chats;
  }
  return group.chats.slice(0, INITIAL_VISIBLE_COUNT);
}

onMounted(() => {
  fetchChatList();
  fetchRepos();
});

function newChatForRepo(repo: string) {
  selectedRepo.value = repo;
  newChat();
}

function formatRelativeTime(dateStr: string) {
  if (!dateStr) return "";
  const now = new Date();
  const d = new Date(dateStr);
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  const diffHr = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}

/** Map repo_full_name → display_name for nicer headers */
function repoDisplayName(repoFullName: string): string {
  const match = repos.value.find((r) => r.repo_full_name === repoFullName);
  return match?.display_name || repoFullName || "Unbekannt";
}

/**
 * Build sidebar groups: every connected repo gets a section,
 * even if it has no chats yet. Repos with chats come first,
 * then repos without chats.
 */
const sidebarGroups = computed(() => {
  // Group chats by repo
  const chatsByRepo = new Map<string, typeof chatList.value>();
  for (const chat of chatList.value) {
    const key = chat.repo || "";
    if (!chatsByRepo.has(key)) chatsByRepo.set(key, []);
    chatsByRepo.get(key)!.push(chat);
  }

  // Start with repos that have chats (preserves recency order)
  const groups: {
    repo: string;
    label: string;
    chats: typeof chatList.value;
  }[] = [];
  const seen = new Set<string>();

  for (const [repo, chats] of chatsByRepo) {
    groups.push({ repo, label: repoDisplayName(repo), chats });
    seen.add(repo);
  }

  // Add connected repos that don't have chats yet
  for (const r of repos.value) {
    if (!seen.has(r.repo_full_name)) {
      groups.push({
        repo: r.repo_full_name,
        label: r.display_name,
        chats: [],
      });
    }
  }

  return groups;
});

/** Track which groups are open — all open by default */
const openGroups = ref<Set<string>>(new Set());

watch(
  sidebarGroups,
  (groups) => {
    for (const g of groups) {
      openGroups.value.add(g.repo);
    }
  },
  { immediate: true },
);

function toggleGroup(repo: string) {
  if (openGroups.value.has(repo)) {
    openGroups.value.delete(repo);
  } else {
    openGroups.value.add(repo);
  }
}

/** Delete confirmation */
const deleteDialogOpen = ref(false);
const pendingDeleteId = ref<string | null>(null);

function requestDelete(chatId: string) {
  pendingDeleteId.value = chatId;
  deleteDialogOpen.value = true;
}

function confirmDelete() {
  if (pendingDeleteId.value) {
    deleteChat(pendingDeleteId.value);
    pendingDeleteId.value = null;
  }
  deleteDialogOpen.value = false;
}
</script>

<template>
  <div class="flex h-full flex-col">
    <!-- Section label -->
    <div class="flex items-center justify-between px-3 pt-3 pb-1.5 shrink-0">
      <span class="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Projekte</span>
    </div>

    <ScrollArea class="flex-1 min-h-0">
      <div v-if="chatListLoading" class="flex justify-center py-6">
        <Loader2 class="h-4 w-4 animate-spin text-muted-foreground" />
      </div>

      <!-- No repos connected at all -->
      <div
        v-else-if="repos.length === 0 && chatList.length === 0"
        class="px-3 py-6 text-center space-y-3"
      >
        <p class="text-xs text-muted-foreground">
          Verbinde ein Repository, um loszulegen.
        </p>
        <NuxtLink to="/settings">
          <Button variant="outline" size="sm" class="gap-1.5">
            <Plus class="h-3.5 w-3.5" />
            Repository hinzufügen
          </Button>
        </NuxtLink>
      </div>

      <!-- Sidebar groups -->
      <div v-else class="flex flex-col px-1.5 pb-1.5">
        <Collapsible
          v-for="group in sidebarGroups"
          :key="group.repo"
          :open="openGroups.has(group.repo)"
          @update:open="toggleGroup(group.repo)"
        >
          <!-- Repo group header — whole row is one hover target -->
          <CollapsibleTrigger
            class="flex w-full items-center justify-start gap-1 rounded-md px-1.5 py-[5px] text-left text-[13px] font-medium text-muted-foreground cursor-pointer hover:bg-accent transition-colors group/header"
            :class="selectedRepo === group.repo ? 'text-foreground' : ''"
          >
            <ChevronRight
              class="h-3 w-3 shrink-0 transition-transform duration-200"
              :class="openGroups.has(group.repo) ? 'rotate-90' : ''"
            />
            <FolderGit2 class="h-3.5 w-3.5 shrink-0" />
            <span class="truncate flex-1 min-w-0">{{ group.label }}</span>
            <span
              class="h-5 w-5 shrink-0 opacity-0 group-hover/header:opacity-100 transition-all inline-flex items-center justify-center text-muted-foreground hover:text-foreground"
              @click.stop="newChatForRepo(group.repo)"
              title="Neuer Chat"
            >
              <MessageSquarePlus class="h-3 w-3" />
            </span>
          </CollapsibleTrigger>

          <!-- Chat items for this repo -->
          <CollapsibleContent>
            <!-- Empty repo -->
            <div v-if="group.chats.length === 0" class="relative ml-[11px] pl-[9px]">
              <div class="absolute left-0 top-0 bottom-0 w-px bg-border" />
              <button
                class="flex items-center gap-1.5 w-full rounded-md px-1.5 py-[5px] text-xs text-muted-foreground cursor-pointer hover:bg-accent hover:text-foreground transition-colors"
                @click="newChatForRepo(group.repo)"
              >
                <MessageSquarePlus class="h-3 w-3" />
                Neuer Chat starten
              </button>
            </div>

            <!-- Chat list -->
            <div v-else class="relative ml-[11px] pl-[9px] flex flex-col">
              <div class="absolute left-0 top-0 bottom-0 w-px bg-border" />
              <button
                v-for="chat in visibleChats(group)"
                :key="chat.chat_id"
                class="group flex items-center gap-1 rounded-md px-1.5 py-[5px] text-left text-[13px] leading-snug cursor-pointer transition-colors hover:bg-accent"
                :class="
                  activeChatId === chat.chat_id ? 'bg-accent font-medium' : ''
                "
                @click="loadChat(chat.chat_id)"
              >
                <span class="truncate flex-1 min-w-0">{{ chat.title }}</span>
                <div class="shrink-0 ml-1 relative">
                  <span class="text-[11px] text-muted-foreground tabular-nums transition-opacity group-hover:opacity-0">
                    {{ formatRelativeTime(chat.updated_at) }}
                  </span>
                  <button
                    class="absolute inset-0 flex items-center justify-center opacity-0 cursor-pointer transition-opacity group-hover:opacity-100 text-muted-foreground hover:text-foreground"
                    @click.stop="requestDelete(chat.chat_id)"
                  >
                    <Trash2 class="h-3 w-3" />
                  </button>
                </div>
              </button>

              <!-- Show more / Show less -->
              <button
                v-if="group.chats.length > INITIAL_VISIBLE_COUNT"
                class="rounded-md px-1.5 py-[5px] text-left text-xs text-muted-foreground cursor-pointer hover:bg-accent hover:text-foreground transition-colors"
                @click.stop="toggleShowMore(group.repo)"
              >
                {{ isGroupExpanded(group.repo) ? 'Show less' : `Show more` }}
              </button>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </ScrollArea>
    <!-- Add repo link -->
    <NuxtLink
      to="/settings"
      class="mx-1.5 mb-1.5 flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors mt-auto"
    >
      <Settings class="h-3.5 w-3.5" />
      Repositories verwalten
    </NuxtLink>
    <!-- Delete confirmation dialog -->
    <AlertDialog :open="deleteDialogOpen" @update:open="deleteDialogOpen = $event">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Chat löschen?</AlertDialogTitle>
          <AlertDialogDescription>
            Dieser Chat wird unwiderruflich gelöscht. Diese Aktion kann nicht rückgängig gemacht werden.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel @click="deleteDialogOpen = false">Abbrechen</AlertDialogCancel>
          <AlertDialogAction
            class="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            @click="confirmDelete"
          >
            Löschen
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
