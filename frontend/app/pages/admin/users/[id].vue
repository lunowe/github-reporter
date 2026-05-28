<script setup lang="ts">
import {
  ArrowLeft,
  Loader2,
  Save,
  User,
  Github,
  Mail,
  Coins,
  Hash,
  Activity,
  Ban,
  RotateCcw,
  Gift,
  ShieldCheck,
} from "lucide-vue-next";
import { MODEL_GROUPS } from "~/constants/models";
import type { PlanTier, UserDetail } from "~/composables/useAdminStats";

const route = useRoute();
const userId = computed(() => route.params.id as string);

const { fetchUserDetail, fetchPlans, updateUserLimits, adjustUsage } = useAdminStats();

const detail = ref<UserDetail | null>(null);
const plans = ref<PlanTier[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

// ── Limits editor state ──
const editPlan = ref("free");
const editBudget = ref("");
const editOptIn = ref(false);
const editSuspended = ref(false);
const editModels = ref<string[]>([]);
const saving = ref(false);
const saveError = ref<string | null>(null);
const saved = ref(false);

// ── Usage adjust state ──
const creditAmount = ref("");
const adjustNote = ref("");
const adjusting = ref<"reset" | "credit" | null>(null);
const adjustMsg = ref<string | null>(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [d, p] = await Promise.all([fetchUserDetail(userId.value), fetchPlans()]);
    detail.value = d;
    plans.value = p;
    editPlan.value = d.plan;
    editBudget.value =
      d.plan_overrides?.monthly_budget_usd != null ? String(d.plan_overrides.monthly_budget_usd) : "";
    editOptIn.value = d.extra_usage_opt_in;
    editSuspended.value = d.suspended;
    editModels.value = [...(d.allowed_models || [])];
    saved.value = false;
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Fehler beim Laden";
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const selectedTier = computed(() => plans.value.find((p) => p.key === editPlan.value));

async function saveLimits() {
  saving.value = true;
  saveError.value = null;
  saved.value = false;
  try {
    const budgetNum = editBudget.value.trim() === "" ? null : Number(editBudget.value);
    await updateUserLimits(userId.value, {
      plan: editPlan.value,
      monthly_budget_usd: budgetNum != null && !Number.isNaN(budgetNum) ? budgetNum : null,
      extra_usage_opt_in: editOptIn.value,
      suspended: editSuspended.value,
      allowed_models: editModels.value,
    });
    saved.value = true;
    await load();
  } catch (e: any) {
    saveError.value = e.data?.detail || e.message || "Fehler beim Speichern";
  } finally {
    saving.value = false;
  }
}

async function doReset() {
  adjusting.value = "reset";
  adjustMsg.value = null;
  try {
    const r: any = await adjustUsage(userId.value, { reset: true, note: adjustNote.value });
    adjustMsg.value =
      r.status === "noop" ? "Kein Verbrauch zum Zurücksetzen." : "Verbrauch zurückgesetzt.";
    adjustNote.value = "";
    await load();
  } catch (e: any) {
    adjustMsg.value = e.data?.detail || e.message || "Fehler";
  } finally {
    adjusting.value = null;
  }
}

async function doCredit() {
  const amount = Number(creditAmount.value);
  if (!amount || Number.isNaN(amount) || amount <= 0) {
    adjustMsg.value = "Bitte einen Betrag > 0 eingeben.";
    return;
  }
  adjusting.value = "credit";
  adjustMsg.value = null;
  try {
    await adjustUsage(userId.value, { credit_usd: amount, note: adjustNote.value });
    adjustMsg.value = `Gutschrift über ${formatUsd(amount)} gewährt.`;
    creditAmount.value = "";
    adjustNote.value = "";
    await load();
  } catch (e: any) {
    adjustMsg.value = e.data?.detail || e.message || "Fehler";
  } finally {
    adjusting.value = null;
  }
}

function toggleModel(value: string) {
  const i = editModels.value.indexOf(value);
  if (i === -1) editModels.value.push(value);
  else editModels.value.splice(i, 1);
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

const maxDaily = computed(() =>
  Math.max(0.0001, ...(detail.value?.daily_series.map((d) => d.cost_usd) ?? [0])),
);

const kindLabel: Record<string, string> = {
  chat: "Chat",
  automation: "Automation",
  adjustment: "Korrektur",
};
</script>

<template>
  <main class="mx-auto max-w-3xl px-4 py-8 md:px-6">
    <NuxtLink to="/admin" class="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-4">
      <ArrowLeft class="h-4 w-4" /> Zurück zur Administration
    </NuxtLink>

    <div v-if="loading" class="flex justify-center py-16">
      <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
    </div>

    <p v-else-if="error" class="text-sm text-destructive py-12 text-center">{{ error }}</p>

    <div v-else-if="detail" class="space-y-5">
      <!-- Profile header -->
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <User class="h-5 w-5 text-muted-foreground" />
            <h1 class="text-xl font-bold tracking-tight">{{ detail.display_name }}</h1>
            <Badge v-if="detail.is_admin" variant="default" class="text-[10px]">Admin</Badge>
            <Badge v-else-if="detail.role === 'viewer'" variant="secondary" class="text-[10px]">Viewer</Badge>
            <Badge v-if="detail.suspended" variant="destructive" class="text-[10px]">Gesperrt</Badge>
          </div>
          <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            <span v-if="detail.github_login" class="flex items-center gap-1"><Github class="h-3 w-3" />@{{ detail.github_login }}</span>
            <span v-if="detail.email" class="flex items-center gap-1"><Mail class="h-3 w-3" />{{ detail.email }}</span>
            <span>Beigetreten: {{ formatDate(detail.created_at) }}</span>
            <span>Zuletzt: {{ formatDate(detail.last_seen_at) }}</span>
          </div>
        </div>
      </div>

      <!-- This month -->
      <Card>
        <CardHeader class="pb-2">
          <div class="flex items-center justify-between">
            <CardTitle class="text-base">Diesen Monat</CardTitle>
            <Badge variant="outline" class="text-[10px]">{{ detail.usage.plan_label }}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <AdminUsageBar
            :cost="detail.usage.period_cost_usd"
            :budget="detail.usage.budget_usd"
            :pct-used="detail.usage.pct_used"
            :show-label="true"
          />
          <div class="mt-3 grid grid-cols-3 gap-2 text-center">
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
        </CardContent>
      </Card>

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

      <!-- Daily series -->
      <Card v-if="detail.daily_series.length">
        <CardHeader class="pb-2"><CardTitle class="text-base">Kosten pro Tag (30 Tage)</CardTitle></CardHeader>
        <CardContent>
          <div class="flex items-end gap-0.5 h-20">
            <div
              v-for="d in detail.daily_series"
              :key="d.date"
              class="flex-1 bg-primary/70 rounded-sm hover:bg-primary transition-colors min-h-[2px]"
              :style="{ height: Math.max(2, (d.cost_usd / maxDaily) * 100) + '%' }"
              :title="`${d.date}: ${formatUsd(d.cost_usd)} · ${formatTokens(d.total_tokens)} Tokens`"
            />
          </div>
        </CardContent>
      </Card>

      <div class="grid md:grid-cols-2 gap-4">
        <!-- By model -->
        <Card v-if="detail.by_model.length">
          <CardHeader class="pb-2"><CardTitle class="text-base">Nach Modell (Monat)</CardTitle></CardHeader>
          <CardContent class="space-y-1.5">
            <div v-for="m in detail.by_model" :key="m.provider + m.model" class="flex items-center justify-between text-xs">
              <span class="font-mono truncate mr-2">{{ m.model }}</span>
              <span class="text-muted-foreground tabular-nums shrink-0">{{ formatUsd(m.cost_usd) }} · {{ formatTokens(m.total_tokens) }}</span>
            </div>
          </CardContent>
        </Card>

        <!-- Invitees -->
        <Card v-if="detail.invitees.length">
          <CardHeader class="pb-2"><CardTitle class="text-base">Eingeladene ({{ detail.invitees.length }})</CardTitle></CardHeader>
          <CardContent class="space-y-1.5">
            <div v-for="inv in detail.invitees" :key="inv.id" class="flex items-center justify-between text-xs">
              <span class="truncate mr-2">{{ inv.display_name || inv.email }}</span>
              <span class="text-muted-foreground tabular-nums shrink-0">{{ formatUsd(inv.period_cost_usd) }} · {{ formatTokens(inv.period_tokens) }}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      <!-- Recent runs -->
      <Card v-if="detail.recent_runs.length">
        <CardHeader class="pb-2"><CardTitle class="text-base">Letzte Läufe</CardTitle></CardHeader>
        <CardContent>
          <div class="space-y-1 max-h-48 overflow-y-auto">
            <div v-for="(r, i) in detail.recent_runs" :key="i" class="flex items-center justify-between text-[11px] gap-2">
              <span class="flex items-center gap-1.5 min-w-0">
                <Badge variant="outline" class="text-[9px] px-1 py-0">{{ kindLabel[r.kind] || r.kind }}</Badge>
                <span class="truncate text-muted-foreground">{{ r.repo || "—" }}</span>
              </span>
              <span class="tabular-nums shrink-0" :class="r.cost_usd < 0 ? 'text-emerald-600' : 'text-muted-foreground'">
                {{ formatUsd(r.cost_usd) }} · {{ formatDate(r.created_at) }}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      <!-- ── Controls: Tarif & Limits ── -->
      <Card class="border-primary/30">
        <CardHeader class="pb-3">
          <CardTitle class="text-base flex items-center gap-2"><ShieldCheck class="h-4 w-4" /> Tarif &amp; Limits</CardTitle>
          <CardDescription>Tarif, Budget, Mehrverbrauch, Sperre und erlaubte Modelle festlegen.</CardDescription>
        </CardHeader>
        <CardContent class="space-y-4">
          <div class="grid sm:grid-cols-2 gap-3">
            <div class="space-y-1">
              <Label class="text-xs">Tarif</Label>
              <Select v-model="editPlan">
                <SelectTrigger class="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="p in plans" :key="p.key" :value="p.key">
                    {{ p.label }}
                    <span class="text-muted-foreground">({{ p.monthly_budget_usd != null ? "$" + p.monthly_budget_usd : "unbegrenzt" }})</span>
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

          <label class="flex items-center justify-between gap-2 rounded-md border px-3 py-2 cursor-pointer">
            <div class="min-w-0">
              <div class="text-xs font-medium">Mehrverbrauch erlauben</div>
              <div class="text-[10px] text-muted-foreground">Pay-per-token über das Budget hinaus (wird abgerechnet).</div>
            </div>
            <Switch v-model="editOptIn" />
          </label>

          <label class="flex items-center justify-between gap-2 rounded-md border px-3 py-2 cursor-pointer"
                 :class="editSuspended ? 'border-destructive/50 bg-destructive/5' : ''">
            <div class="min-w-0">
              <div class="text-xs font-medium flex items-center gap-1.5">
                <Ban class="h-3.5 w-3.5" /> Konto sperren
              </div>
              <div class="text-[10px] text-muted-foreground">Blockiert sofort alle neuen Chat-Läufe (unabhängig vom Budget).</div>
            </div>
            <Switch v-model="editSuspended" />
          </label>

          <div class="space-y-1.5">
            <Label class="text-xs">Erlaubte Modelle</Label>
            <p class="text-[10px] text-muted-foreground">Keine Auswahl = alle Modelle erlaubt.</p>
            <div class="space-y-2 mt-1">
              <div v-for="g in MODEL_GROUPS" :key="g.provider">
                <div class="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">{{ g.provider }}</div>
                <div class="flex flex-wrap gap-1.5 mt-1">
                  <button
                    v-for="m in g.models"
                    :key="m.value"
                    type="button"
                    class="text-xs rounded-md border px-2 py-1 transition-colors"
                    :class="editModels.includes(m.value) ? 'border-primary bg-primary/10 text-primary' : 'hover:bg-accent'"
                    @click="toggleModel(m.value)"
                  >
                    {{ m.label }}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <div class="flex items-center justify-between pt-1">
            <p v-if="saveError" class="text-xs text-destructive">{{ saveError }}</p>
            <p v-else-if="saved" class="text-xs text-emerald-600">Gespeichert.</p>
            <span v-else />
            <Button size="sm" class="gap-2" :disabled="saving" @click="saveLimits">
              <Loader2 v-if="saving" class="h-4 w-4 animate-spin" />
              <Save v-else class="h-4 w-4" />
              Speichern
            </Button>
          </div>
        </CardContent>
      </Card>

      <!-- ── Controls: Nutzung anpassen ── -->
      <Card>
        <CardHeader class="pb-3">
          <CardTitle class="text-base flex items-center gap-2"><Coins class="h-4 w-4" /> Nutzung anpassen</CardTitle>
          <CardDescription>Monatsverbrauch zurücksetzen oder eine Gutschrift gewähren (als Korrektur protokolliert).</CardDescription>
        </CardHeader>
        <CardContent class="space-y-3">
          <div class="space-y-1">
            <Label class="text-xs">Notiz (optional)</Label>
            <Input v-model="adjustNote" placeholder="z.B. Kulanz-Gutschrift, Test" />
          </div>
          <div class="flex flex-wrap items-end gap-3">
            <Button variant="outline" size="sm" class="gap-2" :disabled="adjusting !== null" @click="doReset">
              <Loader2 v-if="adjusting === 'reset'" class="h-4 w-4 animate-spin" />
              <RotateCcw v-else class="h-4 w-4" />
              Verbrauch zurücksetzen
            </Button>

            <div class="flex items-end gap-2">
              <div class="space-y-1">
                <Label class="text-xs">Gutschrift (USD)</Label>
                <Input v-model="creditAmount" type="number" min="0" step="1" placeholder="0.00" class="w-28" />
              </div>
              <Button variant="outline" size="sm" class="gap-2" :disabled="adjusting !== null" @click="doCredit">
                <Loader2 v-if="adjusting === 'credit'" class="h-4 w-4 animate-spin" />
                <Gift v-else class="h-4 w-4" />
                Gutschrift gewähren
              </Button>
            </div>
          </div>
          <p v-if="adjustMsg" class="text-xs text-muted-foreground">{{ adjustMsg }}</p>
        </CardContent>
      </Card>
    </div>
  </main>
</template>
