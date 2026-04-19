<script setup lang="ts">
import {
  Gauge,
  RefreshCw,
  Loader2,
  AlertCircle,
  Clock,
  Search,
  Database,
  CircleCheck,
  CircleAlert,
  TriangleAlert,
} from "lucide-vue-next";
import type { RateLimitBucket } from "~/types/api";

/**
 * GitHub API rate-limit dashboard card.
 *
 * Shows remaining quota across the three GitHub buckets (core / search /
 * graphql), with per-bucket progress bars and a live countdown to reset.
 * Auto-refreshes every 60 seconds — the /rate_limit endpoint does not
 * itself consume quota, so polling is safe.
 */

const { info, loading, error, lastFetched, fetchRateLimit } = useRateLimit({
  pollMs: 60_000,
});

// Live-updating "now" — drives countdown re-computation once per second.
const now = ref(Date.now());
let tickTimer: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  tickTimer = setInterval(() => {
    now.value = Date.now();
  }, 1000);
});

onBeforeUnmount(() => {
  if (tickTimer) clearInterval(tickTimer);
});

// ── Bucket modeling ────────────────────────────────────────────────────

interface BucketView {
  key: "core" | "search" | "graphql";
  label: string;
  description: string;
  icon: any;
  data: RateLimitBucket | null;
}

const buckets = computed<BucketView[]>(() => [
  {
    key: "core",
    label: "Core",
    description: "REST API (Commits, PRs, Issues, Repos …)",
    icon: Database,
    data: info.value?.core ?? null,
  },
  {
    key: "search",
    label: "Search",
    description: "/search/* Endpoints",
    icon: Search,
    data: info.value?.search ?? null,
  },
  {
    key: "graphql",
    label: "GraphQL",
    description: "GraphQL v4 API",
    icon: Gauge,
    data: info.value?.graphql ?? null,
  },
]);

// ── Helpers ────────────────────────────────────────────────────────────

function pct(bucket: RateLimitBucket | null): number {
  if (!bucket || bucket.limit === 0) return 0;
  return Math.max(0, Math.min(100, (bucket.remaining / bucket.limit) * 100));
}

function status(bucket: RateLimitBucket | null): "ok" | "warn" | "crit" {
  const p = pct(bucket);
  if (p <= 10) return "crit";
  if (p <= 30) return "warn";
  return "ok";
}

function barColor(bucket: RateLimitBucket | null): string {
  const s = status(bucket);
  if (s === "crit") return "bg-red-500";
  if (s === "warn") return "bg-yellow-500";
  return "bg-emerald-500";
}

function statusIcon(bucket: RateLimitBucket | null) {
  const s = status(bucket);
  if (s === "crit") return TriangleAlert;
  if (s === "warn") return CircleAlert;
  return CircleCheck;
}

function statusColor(bucket: RateLimitBucket | null): string {
  const s = status(bucket);
  if (s === "crit") return "text-red-500";
  if (s === "warn") return "text-yellow-500";
  return "text-emerald-500";
}

function countdown(resetsAt: string | null): string {
  if (!resetsAt) return "–";
  const target = new Date(resetsAt).getTime();
  const diff = target - now.value;
  if (diff <= 0) return "jetzt";
  const totalSec = Math.floor(diff / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function formatNumber(n: number): string {
  return n.toLocaleString("de-DE");
}

// ── Top-level summary (driven by Core bucket, the most relevant one) ──

const headlineStatus = computed(() => status(info.value?.core ?? null));

const headlineBadge = computed(() => {
  if (headlineStatus.value === "crit")
    return { label: "Kritisch", cls: "border-red-500/50 text-red-500 bg-red-500/10" };
  if (headlineStatus.value === "warn")
    return { label: "Knapp", cls: "border-yellow-500/50 text-yellow-500 bg-yellow-500/10" };
  return { label: "OK", cls: "border-emerald-500/50 text-emerald-500 bg-emerald-500/10" };
});

const lastFetchedAgo = computed(() => {
  if (!lastFetched.value) return "";
  const secs = Math.floor((now.value - lastFetched.value) / 1000);
  if (secs < 5) return "gerade eben";
  if (secs < 60) return `vor ${secs}s`;
  const mins = Math.floor(secs / 60);
  return `vor ${mins}m`;
});
</script>

<template>
  <Card>
    <CardHeader class="pb-3">
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 min-w-0">
          <div class="rounded-md bg-primary/10 p-1.5 shrink-0">
            <Gauge class="h-4 w-4 text-primary" />
          </div>
          <div class="min-w-0">
            <CardTitle class="text-base">GitHub API Quota</CardTitle>
            <CardDescription class="text-xs mt-0.5">
              Verbrauch deines persönlichen API-Tokens
            </CardDescription>
          </div>
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          <Badge
            v-if="info"
            variant="outline"
            class="text-[10px] px-1.5 py-0 h-5"
            :class="headlineBadge.cls"
          >
            {{ headlineBadge.label }}
          </Badge>
          <Button
            variant="ghost"
            size="icon"
            class="h-7 w-7 text-muted-foreground"
            :disabled="loading"
            :title="lastFetchedAgo ? `Aktualisiert ${lastFetchedAgo}` : 'Aktualisieren'"
            @click="fetchRateLimit()"
          >
            <RefreshCw class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" />
          </Button>
        </div>
      </div>
    </CardHeader>

    <CardContent class="pt-0">
      <!-- Loading state -->
      <div
        v-if="loading && !info"
        class="flex items-center justify-center py-8"
      >
        <Loader2 class="h-5 w-5 animate-spin text-muted-foreground" />
      </div>

      <!-- Error state -->
      <div v-else-if="error && !info" class="py-4 text-center">
        <AlertCircle class="h-5 w-5 text-destructive mx-auto mb-2" />
        <p class="text-sm text-destructive">{{ error }}</p>
        <Button variant="ghost" size="sm" class="mt-2" @click="fetchRateLimit()">
          Erneut versuchen
        </Button>
      </div>

      <!-- Loaded -->
      <div v-else-if="info" class="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div
          v-for="b in buckets"
          :key="b.key"
          class="rounded-lg border px-3 py-2.5"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-1.5 min-w-0">
              <component :is="b.icon" class="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <span class="text-xs font-medium truncate" :title="b.description">
                {{ b.label }}
              </span>
            </div>
            <component
              :is="statusIcon(b.data)"
              class="h-3.5 w-3.5 shrink-0"
              :class="statusColor(b.data)"
            />
          </div>

          <div v-if="b.data" class="mt-1.5">
            <div class="flex items-baseline gap-1">
              <span class="text-lg font-bold tracking-tight tabular-nums">
                {{ formatNumber(b.data.remaining) }}
              </span>
              <span class="text-[11px] text-muted-foreground tabular-nums">
                / {{ formatNumber(b.data.limit) }}
              </span>
            </div>

            <!-- Progress bar -->
            <div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                class="h-full transition-all duration-500"
                :class="barColor(b.data)"
                :style="{ width: pct(b.data) + '%' }"
              />
            </div>

            <div class="mt-1.5 flex items-center justify-between text-[10px] text-muted-foreground">
              <span>{{ pct(b.data).toFixed(0) }}% frei</span>
              <span class="flex items-center gap-0.5 tabular-nums" :title="b.data.resets_at || ''">
                <Clock class="h-2.5 w-2.5" />
                {{ countdown(b.data.resets_at) }}
              </span>
            </div>
          </div>

          <div v-else class="mt-1.5 text-xs text-muted-foreground">
            Nicht verfügbar
          </div>
        </div>
      </div>

      <!-- Footer: auto-refresh hint -->
      <p
        v-if="info"
        class="mt-3 text-[10px] text-muted-foreground/70 text-right"
      >
        Automatisch aktualisiert alle 60&nbsp;s · {{ lastFetchedAgo }}
      </p>
    </CardContent>
  </Card>
</template>
