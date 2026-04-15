<script setup lang="ts">
import {
  GitPullRequest,
  CircleDot,
  GitCommit,
  Activity,
  Loader2,
  RefreshCw,
} from "lucide-vue-next";

const { apiFetch } = useApi();
const { selectedRepo } = useChat();

const stats = ref<any>(null);
const loading = ref(false);
const source = ref<"cache" | "fresh" | null>(null);
const error = ref<string | null>(null);

async function fetchStats(refresh = false) {
  if (!selectedRepo.value) return;

  loading.value = true;
  error.value = null;

  try {
    const params = new URLSearchParams({
      repo: selectedRepo.value,
      ...(refresh ? { refresh: "true" } : {}),
    });
    const data = await apiFetch<{ source: string; summary: any }>(
      `/api/dashboard/summary?${params}`
    );
    stats.value = data.summary;
    source.value = data.source as "cache" | "fresh";
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Fehler beim Laden";
  } finally {
    loading.value = false;
  }
}

watch(
  selectedRepo,
  () => {
    if (selectedRepo.value) fetchStats();
  },
  { immediate: true }
);

const cards = computed(() => {
  if (!stats.value) return [];
  return [
    {
      label: "Offene PRs",
      value: stats.value.open_prs ?? "–",
      icon: GitPullRequest,
      color: "text-blue-500",
    },
    {
      label: "Offene Issues",
      value: stats.value.open_issues ?? "–",
      icon: CircleDot,
      color: "text-orange-500",
    },
    {
      label: "Branches",
      value: stats.value.branch_count ?? "–",
      icon: GitCommit,
      color: "text-purple-500",
    },
    {
      label: "CI Status",
      value: stats.value.latest_ci_run?.conclusion ?? "–",
      icon: Activity,
      color:
        stats.value.latest_ci_run?.conclusion === "success"
          ? "text-green-500"
          : "text-red-500",
    },
  ];
});
</script>

<template>
  <div>
    <div v-if="loading" class="flex items-center justify-center py-8">
      <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
    </div>

    <div v-else-if="error" class="text-sm text-destructive text-center py-4">
      {{ error }}
    </div>

    <div
      v-else-if="!selectedRepo"
      class="text-sm text-muted-foreground text-center py-8"
    >
      Bitte wähle ein Repository aus.
    </div>

    <template v-else>
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card v-for="card in cards" :key="card.label">
          <CardHeader class="flex flex-row items-center justify-between pb-2">
            <CardTitle class="text-sm font-medium text-muted-foreground">
              {{ card.label }}
            </CardTitle>
            <component :is="card.icon" class="h-4 w-4" :class="card.color" />
          </CardHeader>
          <CardContent>
            <div class="text-2xl font-bold">{{ card.value }}</div>
          </CardContent>
        </Card>
      </div>

      <div class="mt-4 flex items-center justify-center gap-3">
        <div
          v-if="stats?.last_commit"
          class="text-xs text-muted-foreground"
        >
          Letzter Commit: {{ stats.last_commit.message }}
          <span class="ml-1"
            >({{ stats.last_commit.author }},
            {{ stats.last_commit.date }})</span
          >
        </div>
        <Button
          variant="ghost"
          size="sm"
          class="text-xs text-muted-foreground h-6 px-2"
          :disabled="loading"
          @click="fetchStats(true)"
        >
          <RefreshCw class="h-3 w-3 mr-1" />
          Aktualisieren
        </Button>
        <Badge
          v-if="source === 'cache'"
          variant="outline"
          class="text-[10px] px-1.5 py-0"
        >
          Cache
        </Badge>
      </div>
    </template>
  </div>
</template>
