<script setup lang="ts">
import { Loader2, Save, User, Github, Mail, Coins, Hash, Activity } from "lucide-vue-next";
import type { PlanTier, UserDetail } from "~/composables/useAdminStats";

const props = defineProps<{
  open: boolean;
  userId: string | null;
  plans: PlanTier[];
}>();

const emit = defineEmits<{
  (e: "update:open", v: boolean): void;
  (e: "updated"): void;
}>();

const { fetchUserDetail, updateUserPlan } = useAdminStats();

const detail = ref<UserDetail | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);

// ── Plan editor state ──
const editPlan = ref<string>("free");
const editBudget = ref<string>(""); // empty = use tier default
const editOptIn = ref<boolean>(false);
const saving = ref(false);
const saveError = ref<string | null>(null);
const saved = ref(false);

async function load() {
  if (!props.userId) return;
  loading.value = true;
  error.value = null;
  detail.value = null;
  try {
    const d = await fetchUserDetail(props.userId);
    detail.value = d;
    editPlan.value = d.plan;
    editBudget.value =
      d.plan_overrides?.monthly_budget_usd != null
        ? String(d.plan_overrides.monthly_budget_usd)
        : "";
    editOptIn.value = d.extra_usage_opt_in;
    saved.value = false;
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Fehler beim Laden";
  } finally {
    loading.value = false;
  }
}

watch(
  () => [props.open, props.userId],
  ([isOpen]) => {
    if (isOpen && props.userId) load();
  },
);

const selectedTier = computed(() => props.plans.find((p) => p.key === editPlan.value));

async function savePlan() {
  if (!props.userId) return;
  saving.value = true;
  saveError.value = null;
  saved.value = false;
  try {
    const budgetNum = editBudget.value.trim() === "" ? null : Number(editBudget.value);
    await updateUserPlan(props.userId, {
      plan: editPlan.value,
      monthly_budget_usd: budgetNum != null && !Number.isNaN(budgetNum) ? budgetNum : null,
      extra_usage_opt_in: editOptIn.value,
    });
    saved.value = true;
    emit("updated");
    // Reflect new numbers in the detail view.
    await load();
  } catch (e: any) {
    saveError.value = e.data?.detail || e.message || "Fehler beim Speichern";
  } finally {
    saving.value = false;
  }
}

function formatDate(d: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Daily series: scale bars to the max cost in the window.
const maxDaily = computed(() =>
  Math.max(0.0001, ...(detail.value?.daily_series.map((d) => d.cost_usd) ?? [0])),
);

const kindLabel: Record<string, string> = { chat: "Chat", automation: "Automation" };
</script>

<template>
  <Dialog :open="open" @update:open="(v) => emit('update:open', v)">
    <DialogScrollContent class="sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>Benutzerdetails</DialogTitle>
        <DialogDescription>Nutzung, Kosten und Tarif verwalten.</DialogDescription>
      </DialogHeader>

      <div v-if="loading" class="flex justify-center py-12">
        <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
      </div>

      <p v-else-if="error" class="text-sm text-destructive py-8 text-center">{{ error }}</p>

      <div v-else-if="detail" class="space-y-5">
        <!-- Profile header -->
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <User class="h-4 w-4 text-muted-foreground" />
              <span class="font-semibold">{{ detail.display_name }}</span>
              <Badge v-if="detail.is_admin" variant="default" class="text-[10px]">Admin</Badge>
              <Badge v-else-if="detail.role === 'viewer'" variant="secondary" class="text-[10px]">Viewer</Badge>
            </div>
            <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
              <span v-if="detail.github_login" class="flex items-center gap-1">
                <Github class="h-3 w-3" />@{{ detail.github_login }}
              </span>
              <span v-if="detail.email" class="flex items-center gap-1">
                <Mail class="h-3 w-3" />{{ detail.email }}
              </span>
              <span>Beigetreten: {{ formatDate(detail.created_at) }}</span>
              <span>Zuletzt: {{ formatDate(detail.last_seen_at) }}</span>
            </div>
          </div>
        </div>

        <!-- This month: cost vs budget -->
        <div class="rounded-lg border p-3">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-medium text-muted-foreground">Diesen Monat</span>
            <Badge variant="outline" class="text-[10px]">{{ detail.usage.plan_label }}</Badge>
          </div>
          <AdminUsageBar
            :cost="detail.usage.period_cost_usd"
            :budget="detail.usage.budget_usd"
            :pct-used="detail.usage.pct_used"
            :show-label="true"
          />
          <div class="mt-2 grid grid-cols-3 gap-2 text-center">
            <div>
              <div class="text-sm font-semibold tabular-nums">{{ formatTokens(detail.usage.period_tokens) }}</div>
              <div class="text-[10px] text-muted-foreground">Tokens</div>
            </div>
            <div>
              <div class="text-sm font-semibold tabular-nums">{{ detail.usage.run_count }}</div>
              <div class="text-[10px] text-muted-foreground">Läufe</div>
            </div>
            <div>
              <div class="text-sm font-semibold tabular-nums" :class="detail.usage.overage_usd > 0 ? 'text-red-500' : ''">
                {{ formatUsd(detail.usage.overage_usd) }}
              </div>
              <div class="text-[10px] text-muted-foreground">Mehrverbrauch</div>
            </div>
          </div>
        </div>

        <!-- Lifetime KPIs -->
        <div class="grid grid-cols-3 gap-2">
          <div class="rounded-lg border p-3 text-center">
            <Coins class="h-4 w-4 mx-auto text-muted-foreground mb-1" />
            <div class="text-base font-bold tabular-nums">{{ formatUsd(detail.lifetime.cost_usd) }}</div>
            <div class="text-[10px] text-muted-foreground">Kosten gesamt</div>
          </div>
          <div class="rounded-lg border p-3 text-center">
            <Hash class="h-4 w-4 mx-auto text-muted-foreground mb-1" />
            <div class="text-base font-bold tabular-nums">{{ formatTokens(detail.lifetime.total_tokens) }}</div>
            <div class="text-[10px] text-muted-foreground">Tokens gesamt</div>
          </div>
          <div class="rounded-lg border p-3 text-center">
            <Activity class="h-4 w-4 mx-auto text-muted-foreground mb-1" />
            <div class="text-base font-bold tabular-nums">{{ detail.lifetime.run_count }}</div>
            <div class="text-[10px] text-muted-foreground">Läufe gesamt</div>
          </div>
        </div>

        <!-- Daily series (last 30d) -->
        <div v-if="detail.daily_series.length" class="rounded-lg border p-3">
          <div class="text-xs font-medium text-muted-foreground mb-2">Kosten pro Tag (30 Tage)</div>
          <div class="flex items-end gap-0.5 h-16">
            <div
              v-for="d in detail.daily_series"
              :key="d.date"
              class="flex-1 bg-primary/70 rounded-sm hover:bg-primary transition-colors min-h-[2px]"
              :style="{ height: Math.max(2, (d.cost_usd / maxDaily) * 100) + '%' }"
              :title="`${d.date}: ${formatUsd(d.cost_usd)} · ${formatTokens(d.total_tokens)} Tokens`"
            />
          </div>
        </div>

        <!-- By model -->
        <div v-if="detail.by_model.length" class="rounded-lg border p-3">
          <div class="text-xs font-medium text-muted-foreground mb-2">Nach Modell (diesen Monat)</div>
          <div class="space-y-1.5">
            <div
              v-for="m in detail.by_model"
              :key="m.provider + m.model"
              class="flex items-center justify-between text-xs"
            >
              <span class="font-mono truncate mr-2">{{ m.model }}</span>
              <span class="text-muted-foreground tabular-nums shrink-0">
                {{ formatUsd(m.cost_usd) }} · {{ formatTokens(m.total_tokens) }} · {{ m.run_count }}×
              </span>
            </div>
          </div>
        </div>

        <!-- Invitees -->
        <div v-if="detail.invitees.length" class="rounded-lg border p-3">
          <div class="text-xs font-medium text-muted-foreground mb-2">
            Eingeladene Benutzer ({{ detail.invitees.length }})
          </div>
          <div class="space-y-1.5">
            <div
              v-for="inv in detail.invitees"
              :key="inv.id"
              class="flex items-center justify-between text-xs"
            >
              <span class="truncate mr-2">{{ inv.display_name || inv.email }}</span>
              <span class="text-muted-foreground tabular-nums shrink-0">
                {{ formatUsd(inv.period_cost_usd) }} · {{ formatTokens(inv.period_tokens) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Recent runs -->
        <div v-if="detail.recent_runs.length" class="rounded-lg border p-3">
          <div class="text-xs font-medium text-muted-foreground mb-2">Letzte Läufe</div>
          <div class="space-y-1 max-h-40 overflow-y-auto">
            <div
              v-for="(r, i) in detail.recent_runs"
              :key="i"
              class="flex items-center justify-between text-[11px] gap-2"
            >
              <span class="flex items-center gap-1.5 min-w-0">
                <Badge variant="outline" class="text-[9px] px-1 py-0">{{ kindLabel[r.kind] || r.kind }}</Badge>
                <span class="truncate text-muted-foreground">{{ r.repo || "—" }}</span>
              </span>
              <span class="text-muted-foreground tabular-nums shrink-0">
                {{ formatUsd(r.cost_usd) }} · {{ formatDate(r.created_at) }}
              </span>
            </div>
          </div>
        </div>

        <!-- Plan & limits editor -->
        <div class="rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-3">
          <div class="text-sm font-medium">Tarif &amp; Limits</div>

          <div class="grid grid-cols-2 gap-3">
            <div class="space-y-1">
              <Label class="text-xs">Tarif</Label>
              <Select v-model="editPlan">
                <SelectTrigger class="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="p in plans" :key="p.key" :value="p.key">
                    {{ p.label }}
                    <span class="text-muted-foreground">
                      ({{ p.monthly_budget_usd != null ? "$" + p.monthly_budget_usd : "unbegrenzt" }})
                    </span>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div class="space-y-1">
              <Label class="text-xs">Budget-Override (USD/Monat)</Label>
              <Input
                v-model="editBudget"
                type="number"
                min="0"
                step="1"
                :placeholder="selectedTier?.monthly_budget_usd != null ? `Standard: $${selectedTier.monthly_budget_usd}` : 'unbegrenzt'"
              />
            </div>
          </div>

          <label class="flex items-center justify-between gap-2 rounded-md border bg-background px-3 py-2 cursor-pointer">
            <div class="min-w-0">
              <div class="text-xs font-medium">Mehrverbrauch erlauben</div>
              <div class="text-[10px] text-muted-foreground">
                Pay-per-token über das Budget hinaus (wird abgerechnet).
              </div>
            </div>
            <Switch v-model="editOptIn" />
          </label>

          <div class="flex items-center justify-between">
            <p v-if="saveError" class="text-xs text-destructive">{{ saveError }}</p>
            <p v-else-if="saved" class="text-xs text-emerald-600">Gespeichert.</p>
            <span v-else />
            <Button size="sm" class="gap-2" :disabled="saving" @click="savePlan">
              <Loader2 v-if="saving" class="h-4 w-4 animate-spin" />
              <Save v-else class="h-4 w-4" />
              Speichern
            </Button>
          </div>
        </div>
      </div>
    </DialogScrollContent>
  </Dialog>
</template>
