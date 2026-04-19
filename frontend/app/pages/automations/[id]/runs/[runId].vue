<script setup lang="ts">
import {
  ArrowLeft,
  Loader2,
  CheckCircle2,
  XCircle,
  CircleDashed,
  Clock,
  Mail,
  GitBranch,
  Copy,
  Check,
  Sparkles,
} from "lucide-vue-next";
import { formatDate } from "~/composables/useAutomations";
import type { Automation, AutomationRun } from "~/types/api";

const route = useRoute();
const automationId = computed(() => route.params.id as string);
const runId = computed(() => route.params.runId as string);

const { getRun, getAutomation } = useAutomations();
const { render: renderMarkdown } = useMarkdown();

const run = ref<AutomationRun | null>(null);
const automation = ref<Automation | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const pollHandle = ref<ReturnType<typeof setInterval> | null>(null);
const copiedStep = ref<number | null>(null);
const copiedFinal = ref(false);

// Show the composed final-output panel only when the user opted into a
// non-trivial format (merge / template). For "last_step", the last step
// card is already the final output — no need to duplicate it.
const showFinal = computed(() => {
  const fmt = automation.value?.final_output_format;
  return (
    !!run.value?.final_output &&
    (fmt === "merge" || fmt === "template")
  );
});

async function fetchRun() {
  try {
    run.value = await getRun(automationId.value, runId.value);
    // Stop polling once terminal
    if (run.value.status === "completed" || run.value.status === "failed") {
      if (pollHandle.value) {
        clearInterval(pollHandle.value);
        pollHandle.value = null;
      }
    }
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Run nicht gefunden";
    if (pollHandle.value) {
      clearInterval(pollHandle.value);
      pollHandle.value = null;
    }
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  // Fetch the parent automation once to know its `final_output_format`.
  // Failure here is non-fatal — the page still renders the run.
  try {
    automation.value = await getAutomation(automationId.value);
  } catch {
    automation.value = null;
  }
  fetchRun();
  // Poll every 2s while the run may still be active
  pollHandle.value = setInterval(fetchRun, 2000);
});

onBeforeUnmount(() => {
  if (pollHandle.value) clearInterval(pollHandle.value);
});

const statusMeta = computed(() => {
  if (!run.value) return null;
  switch (run.value.status) {
    case "completed":
      return { icon: CheckCircle2, classes: "text-emerald-600", label: "Erfolgreich abgeschlossen" };
    case "failed":
      return { icon: XCircle, classes: "text-destructive", label: "Fehlgeschlagen" };
    case "running":
      return { icon: Loader2, classes: "animate-spin text-blue-600", label: "Läuft gerade" };
    default:
      return { icon: CircleDashed, classes: "text-muted-foreground", label: "Wartet" };
  }
});

async function copyStep(step: AutomationRun["step_results"][number]) {
  try {
    await navigator.clipboard.writeText(step.output);
    copiedStep.value = step.order;
    setTimeout(() => (copiedStep.value = null), 1500);
  } catch {
    // ignore
  }
}

async function copyFinal() {
  if (!run.value?.final_output) return;
  try {
    await navigator.clipboard.writeText(run.value.final_output);
    copiedFinal.value = true;
    setTimeout(() => (copiedFinal.value = false), 1500);
  } catch {
    // ignore
  }
}
</script>

<template>
  <main class="mx-auto max-w-4xl px-4 py-8 md:px-6">
    <NuxtLink :to="`/automations/${automationId}`">
      <Button variant="ghost" size="sm" class="mb-3 -ml-2 gap-1">
        <ArrowLeft class="h-4 w-4" />
        Zurück zur Automation
      </Button>
    </NuxtLink>

    <div v-if="loading" class="flex justify-center py-16">
      <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
    </div>

    <Alert v-else-if="error" variant="destructive">
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <template v-else-if="run">
      <!-- Header -->
      <div class="mb-6">
        <div class="flex items-center gap-2 mb-2">
          <h1 class="text-2xl font-bold tracking-tight">
            {{ run.automation_name }}
          </h1>
          <Badge variant="outline" class="text-xs font-normal">
            {{ run.trigger === "schedule" ? "Zeitplan" : "Manuell" }}
          </Badge>
        </div>

        <div
          v-if="statusMeta"
          class="flex items-center gap-2 text-sm"
          :class="statusMeta.classes"
        >
          <component :is="statusMeta.icon" class="h-4 w-4" />
          {{ statusMeta.label }}
        </div>

        <div class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span class="inline-flex items-center gap-1">
            <Clock class="h-3.5 w-3.5" />
            Gestartet: {{ formatDate(run.started_at) }}
          </span>
          <span v-if="run.completed_at" class="inline-flex items-center gap-1">
            Beendet: {{ formatDate(run.completed_at) }}
          </span>
          <span v-if="run.email_sent" class="inline-flex items-center gap-1">
            <Mail class="h-3.5 w-3.5" />
            E-Mail versendet
          </span>
        </div>
      </div>

      <Alert v-if="run.error" variant="destructive" class="mb-6">
        <AlertDescription>{{ run.error }}</AlertDescription>
      </Alert>

      <!-- Composed final output (shown for "merge" / "template" formats) -->
      <Card v-if="showFinal" class="mb-6 border-primary/30">
        <CardHeader class="pb-3">
          <div class="flex items-start justify-between gap-3">
            <div class="flex items-center gap-2">
              <Sparkles class="h-4 w-4 text-primary" />
              <CardTitle class="text-base">Finales Ergebnis</CardTitle>
            </div>
            <Button
              variant="ghost"
              size="icon"
              class="h-7 w-7"
              @click="copyFinal"
            >
              <Check
                v-if="copiedFinal"
                class="h-3.5 w-3.5 text-emerald-600"
              />
              <Copy v-else class="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div
            class="prose prose-sm max-w-none dark:prose-invert"
            v-html="renderMarkdown(run.final_output)"
          />
        </CardContent>
      </Card>

      <h2
        v-if="showFinal && run.step_results.length > 0"
        class="text-sm font-medium text-muted-foreground mb-3"
      >
        Schritte im Detail
      </h2>

      <!-- Step results -->
      <div class="space-y-4">
        <Card v-for="step in run.step_results" :key="step.order">
          <CardHeader class="pb-3">
            <div class="flex items-start justify-between gap-3">
              <div class="flex items-center gap-2 flex-wrap">
                <Badge variant="secondary">Schritt {{ step.order }}</Badge>
                <CardTitle class="text-base">{{ step.name }}</CardTitle>
                <Badge variant="outline" class="gap-1 text-xs font-normal">
                  <GitBranch class="h-3 w-3" />
                  {{ step.repo }}
                </Badge>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span class="text-xs text-muted-foreground">
                  {{ (step.duration_ms / 1000).toFixed(1) }}s
                </span>
                <Button
                  v-if="step.output && !step.error"
                  variant="ghost"
                  size="icon"
                  class="h-7 w-7"
                  @click="copyStep(step)"
                >
                  <Check
                    v-if="copiedStep === step.order"
                    class="h-3.5 w-3.5 text-emerald-600"
                  />
                  <Copy v-else class="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>

            <details class="mt-2 text-xs">
              <summary class="cursor-pointer text-muted-foreground hover:text-foreground">
                Prompt anzeigen
              </summary>
              <pre
                class="mt-2 whitespace-pre-wrap rounded bg-muted p-2 font-mono text-xs leading-relaxed"
              >{{ step.prompt }}</pre>
            </details>
          </CardHeader>

          <CardContent>
            <Alert v-if="step.error" variant="destructive" class="text-xs">
              <AlertDescription>{{ step.error }}</AlertDescription>
            </Alert>
            <div
              v-else-if="step.output"
              class="prose prose-sm max-w-none dark:prose-invert"
              v-html="renderMarkdown(step.output)"
            />
            <div v-else class="text-sm text-muted-foreground italic">
              Kein Output.
            </div>
          </CardContent>
        </Card>

        <!-- Pending step placeholder while still running -->
        <Card v-if="run.status === 'running'" class="border-dashed">
          <CardContent class="p-4 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 class="h-4 w-4 animate-spin" />
            Nächster Schritt wird ausgeführt …
          </CardContent>
        </Card>
      </div>
    </template>
  </main>
</template>
