<script setup lang="ts">
import {
  GitPullRequest,
  CircleDot,
  GitBranch,
  GitCommit,
  Star,
  GitFork,
  RefreshCw,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  Tag,
} from "lucide-vue-next";

const props = defineProps<{
  repo: string;
  displayName: string;
}>();

const { apiFetch } = useApi();

const stats = ref<any>(null);
const details = ref<any>(null);
const loading = ref(false);
const detailsLoading = ref(false);
const source = ref<"cache" | "fresh" | null>(null);
const error = ref<string | null>(null);

async function fetchStats(refresh = false) {
  loading.value = true;
  error.value = null;
  try {
    const params = new URLSearchParams({
      repo: props.repo,
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

async function fetchDetails() {
  detailsLoading.value = true;
  try {
    const params = new URLSearchParams({ repo: props.repo });
    details.value = await apiFetch<any>(`/api/dashboard/details?${params}`);
  } catch {
    // Non-critical — card still works without details
  } finally {
    detailsLoading.value = false;
  }
}

onMounted(() => {
  fetchStats();
  fetchDetails();
});

// ── CI status helpers ───────────────────────────────────────────────────

const ciConclusion = computed(() => stats.value?.latest_ci_run?.conclusion);

const ciDotClass = computed(() => {
  if (ciConclusion.value === "success") return "bg-green-500";
  if (ciConclusion.value === "failure") return "bg-red-500";
  return "bg-yellow-500";
});

const ciIcon = computed(() => {
  if (ciConclusion.value === "success") return CheckCircle2;
  if (ciConclusion.value === "failure") return XCircle;
  return AlertCircle;
});

const ciLabel = computed(() => {
  if (ciConclusion.value === "success") return "Passing";
  if (ciConclusion.value === "failure") return "Failing";
  return ciConclusion.value || "–";
});

const ciColor = computed(() => {
  if (ciConclusion.value === "success") return "text-green-500";
  if (ciConclusion.value === "failure") return "text-red-500";
  return "text-yellow-500";
});

const ciBg = computed(() => {
  if (ciConclusion.value === "success") return "bg-green-500/10";
  if (ciConclusion.value === "failure") return "bg-red-500/10";
  return "bg-yellow-500/10";
});

// ── Stat cards ──────────────────────────────────────────────────────────

const statCards = computed(() => {
  if (!stats.value) return [];
  return [
    {
      label: "Offene PRs",
      value: stats.value.open_prs ?? "–",
      icon: GitPullRequest,
      color: "text-blue-500",
      bg: "bg-blue-500/10",
    },
    {
      label: "Offene Issues",
      value: stats.value.open_issues ?? "–",
      icon: CircleDot,
      color: "text-orange-500",
      bg: "bg-orange-500/10",
    },
    {
      label: "Branches",
      value: stats.value.branch_count ?? "–",
      icon: GitBranch,
      color: "text-purple-500",
      bg: "bg-purple-500/10",
    },
    {
      label: "CI Status",
      value: ciLabel.value,
      icon: ciIcon.value,
      color: ciColor.value,
      bg: ciBg.value,
    },
  ];
});

// ── Language bar ────────────────────────────────────────────────────────

const LANG_COLORS: Record<string, string> = {
  TypeScript: "#3178c6",
  JavaScript: "#f1e05a",
  Python: "#3572A5",
  Vue: "#41b883",
  HTML: "#e34c26",
  CSS: "#563d7c",
  SCSS: "#c6538c",
  Java: "#b07219",
  Go: "#00ADD8",
  Rust: "#dea584",
  Shell: "#89e051",
  Dockerfile: "#384d54",
  Ruby: "#701516",
  PHP: "#4F5D95",
  C: "#555555",
  "C++": "#f34b7d",
  "C#": "#178600",
  Swift: "#F05138",
  Kotlin: "#A97BFF",
  Dart: "#00B4AB",
};

const languageSegments = computed(() => {
  const langs = details.value?.languages;
  if (!langs || Object.keys(langs).length === 0) return [];

  const total = Object.values(langs).reduce((a: number, b: any) => a + b, 0) as number;
  if (total === 0) return [];

  return Object.entries(langs)
    .sort(([, a], [, b]) => (b as number) - (a as number))
    .map(([name, bytes]) => ({
      name,
      bytes: bytes as number,
      pct: ((bytes as number) / total) * 100,
      color: LANG_COLORS[name] || "#8b8b8b",
    }));
});

// ── Commit activity sparkline ──────────────────────────────────────────

const activityBars = computed(() => {
  const activity = details.value?.commit_activity;
  if (!activity || activity.length === 0) return [];
  // Take last 12 weeks
  const weeks = activity.slice(-12);
  const max = Math.max(...weeks.map((w: any) => w.total), 1);
  return weeks.map((w: any) => ({
    total: w.total,
    height: Math.max((w.total / max) * 100, 4), // min 4% so empty weeks show a sliver
  }));
});

// ── Event icon mapping ─────────────────────────────────────────────────

const EVENT_ICONS: Record<string, any> = {
  push: GitCommit,
  pr: GitPullRequest,
  issue: CircleDot,
  release: Tag,
  branch: GitBranch,
};

// ── Relative time ───────────────────────────────────────────────────────

function relativeTime(dateStr: string): string {
  if (!dateStr) return "";
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "gerade eben";
  if (mins < 60) return `vor ${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `vor ${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `vor ${days}d`;
  const months = Math.floor(days / 30);
  return `vor ${months}mo`;
}
</script>

<template>
  <Card class="overflow-hidden">
    <!-- Loading state -->
    <div v-if="loading && !stats" class="flex items-center justify-center py-12">
      <Loader2 class="h-5 w-5 animate-spin text-muted-foreground" />
    </div>

    <!-- Error state -->
    <div v-else-if="error && !stats" class="p-6 text-center">
      <AlertCircle class="h-5 w-5 text-destructive mx-auto mb-2" />
      <p class="text-sm text-destructive">{{ error }}</p>
      <Button variant="ghost" size="sm" class="mt-2" @click="fetchStats()">
        Erneut versuchen
      </Button>
    </div>

    <!-- Loaded content -->
    <template v-else-if="stats">
      <CardHeader class="pb-3">
        <div class="flex items-center justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2.5">
              <CardTitle class="text-lg truncate">{{ displayName }}</CardTitle>
              <!-- CI health dot -->
              <span
                class="relative flex h-2.5 w-2.5 shrink-0"
                :title="`CI: ${ciLabel}`"
              >
                <span
                  class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-75"
                  :class="ciDotClass"
                  v-if="ciConclusion === 'failure'"
                />
                <span class="relative inline-flex h-2.5 w-2.5 rounded-full" :class="ciDotClass" />
              </span>
            </div>
            <CardDescription v-if="stats.description" class="mt-0.5 line-clamp-1">
              {{ stats.description }}
            </CardDescription>
          </div>
          <div class="flex items-center gap-1.5 shrink-0">
            <Badge v-if="source === 'cache'" variant="outline" class="text-[10px] px-1.5 py-0 h-4">
              Cache
            </Badge>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7 text-muted-foreground"
              :disabled="loading"
              @click="fetchStats(true)"
            >
              <RefreshCw class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" />
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent class="pt-0 space-y-4">
        <!-- Stats grid -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div
            v-for="card in statCards"
            :key="card.label"
            class="rounded-lg border px-3 py-2.5"
          >
            <div class="flex items-center justify-between">
              <span class="text-[11px] text-muted-foreground">{{ card.label }}</span>
              <div class="rounded-md p-1" :class="card.bg">
                <component :is="card.icon" class="h-3.5 w-3.5" :class="card.color" />
              </div>
            </div>
            <div class="mt-1 text-xl font-bold tracking-tight">{{ card.value }}</div>
          </div>
        </div>

        <!-- Commit activity sparkline + Language bar (side by side on desktop) -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3" v-if="details">
          <!-- Commit activity -->
          <div v-if="activityBars.length > 0" class="rounded-lg border px-3 py-2.5">
            <span class="text-[11px] text-muted-foreground">Commit-Aktivität (12 Wochen)</span>
            <div class="mt-2 flex items-end gap-[3px] h-12">
              <div
                v-for="(bar, i) in activityBars"
                :key="i"
                class="flex-1 rounded-sm bg-primary/70 hover:bg-primary transition-colors cursor-default"
                :style="{ height: bar.height + '%' }"
                :title="`${bar.total} Commits`"
              />
            </div>
          </div>

          <!-- Language bar -->
          <div v-if="languageSegments.length > 0" class="rounded-lg border px-3 py-2.5">
            <span class="text-[11px] text-muted-foreground">Sprachen</span>
            <!-- Colored bar -->
            <div class="mt-2 flex h-2 rounded-full overflow-hidden">
              <div
                v-for="lang in languageSegments"
                :key="lang.name"
                :style="{ width: lang.pct + '%', backgroundColor: lang.color }"
                :title="`${lang.name}: ${lang.pct.toFixed(1)}%`"
                class="transition-all"
              />
            </div>
            <!-- Legend -->
            <div class="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
              <div
                v-for="lang in languageSegments.slice(0, 5)"
                :key="lang.name"
                class="flex items-center gap-1 text-[10px] text-muted-foreground"
              >
                <span class="h-2 w-2 rounded-full shrink-0" :style="{ backgroundColor: lang.color }" />
                {{ lang.name }}
                <span class="text-muted-foreground/60">{{ lang.pct.toFixed(0) }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Contributors + Recent activity (side by side) -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3" v-if="details">
          <!-- Contributors -->
          <div v-if="details.contributors?.length" class="rounded-lg border px-3 py-2.5">
            <span class="text-[11px] text-muted-foreground">Top-Contributors</span>
            <div class="mt-2 flex flex-wrap gap-1.5">
              <TooltipProvider :delay-duration="200">
                <Tooltip v-for="c in details.contributors" :key="c.login">
                  <TooltipTrigger as-child>
                    <img
                      :src="c.avatar_url"
                      :alt="c.login"
                      class="h-7 w-7 rounded-full border hover:ring-2 hover:ring-primary/50 transition-all cursor-default"
                    />
                  </TooltipTrigger>
                  <TooltipContent side="top" class="text-xs">
                    {{ c.login }} · {{ c.contributions }} Commits
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
          </div>

          <!-- Recent activity -->
          <div v-if="details.recent_activity?.length" class="rounded-lg border px-3 py-2.5">
            <span class="text-[11px] text-muted-foreground">Letzte Aktivität</span>
            <div class="mt-1.5 space-y-1">
              <div
                v-for="(event, i) in details.recent_activity.slice(0, 5)"
                :key="i"
                class="flex items-start gap-1.5 text-[11px]"
              >
                <component
                  :is="EVENT_ICONS[event.type] || GitCommit"
                  class="h-3 w-3 mt-0.5 shrink-0 text-muted-foreground"
                />
                <span class="flex-1 min-w-0 truncate">{{ event.description }}</span>
                <span class="shrink-0 text-muted-foreground/60">{{ relativeTime(event.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Footer: stars, forks, last commit -->
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
          <div v-if="stats.stars != null" class="flex items-center gap-1">
            <Star class="h-3 w-3" />
            <span>{{ stats.stars }}</span>
          </div>
          <div v-if="stats.forks != null" class="flex items-center gap-1">
            <GitFork class="h-3 w-3" />
            <span>{{ stats.forks }}</span>
          </div>
          <div
            v-if="stats.last_commit"
            class="flex items-center gap-1 min-w-0"
            :class="(stats.stars != null || stats.forks != null) ? 'border-l pl-4' : ''"
          >
            <GitCommit class="h-3 w-3 shrink-0" />
            <span class="truncate">{{ stats.last_commit.message }}</span>
            <span class="shrink-0 text-muted-foreground/60">
              &middot; {{ stats.last_commit.author }} &middot; {{ relativeTime(stats.last_commit.date) }}
            </span>
          </div>
        </div>
      </CardContent>
    </template>
  </Card>
</template>
