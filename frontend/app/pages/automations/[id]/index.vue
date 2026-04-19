<script setup lang="ts">
import {
  ArrowLeft,
  Loader2,
  Play,
  CheckCircle2,
  XCircle,
  CircleDashed,
} from "lucide-vue-next";
import { formatDate } from "~/composables/useAutomations";
import type {
  Automation,
  AutomationCreatePayload,
  AutomationRun,
} from "~/types/api";

const route = useRoute();
const id = computed(() => route.params.id as string);

const { getAutomation, updateAutomation, runNow, listRuns } = useAutomations();

const automation = ref<Automation | null>(null);
const runs = ref<AutomationRun[]>([]);
const loading = ref(true);
const saving = ref(false);
const runningManually = ref(false);
const error = ref<string | null>(null);

async function refresh() {
  try {
    const [a, rs] = await Promise.all([
      getAutomation(id.value),
      listRuns(id.value),
    ]);
    automation.value = a;
    runs.value = rs;
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Automation nicht gefunden";
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);

async function onSubmit(payload: AutomationCreatePayload) {
  saving.value = true;
  error.value = null;
  try {
    automation.value = await updateAutomation(id.value, payload);
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Fehler beim Speichern";
  } finally {
    saving.value = false;
  }
}

async function onRunNow() {
  runningManually.value = true;
  error.value = null;
  try {
    const run = await runNow(id.value);
    await navigateTo(`/automations/${id.value}/runs/${run.id}`);
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Start fehlgeschlagen";
    runningManually.value = false;
  }
}

const statusMeta = (status: AutomationRun["status"]) => {
  switch (status) {
    case "completed":
      return { icon: CheckCircle2, classes: "text-emerald-600", label: "Erfolg" };
    case "failed":
      return { icon: XCircle, classes: "text-destructive", label: "Fehler" };
    case "running":
      return { icon: Loader2, classes: "animate-spin text-blue-600", label: "Läuft" };
    default:
      return { icon: CircleDashed, classes: "text-muted-foreground", label: "Wartet" };
  }
};
</script>

<template>
  <main class="mx-auto max-w-3xl px-4 py-8 md:px-6">
    <NuxtLink to="/automations">
      <Button variant="ghost" size="sm" class="mb-3 -ml-2 gap-1">
        <ArrowLeft class="h-4 w-4" />
        Zurück zu Automationen
      </Button>
    </NuxtLink>

    <div v-if="loading" class="flex justify-center py-16">
      <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
    </div>

    <template v-else-if="automation">
      <div class="mb-6 flex items-start justify-between gap-3">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">
            {{ automation.name }}
          </h1>
          <p v-if="automation.description" class="mt-1 text-sm text-muted-foreground">
            {{ automation.description }}
          </p>
        </div>
        <Button
          class="gap-1.5 shrink-0"
          :disabled="runningManually"
          @click="onRunNow"
        >
          <Loader2 v-if="runningManually" class="h-4 w-4 animate-spin" />
          <Play v-else class="h-4 w-4" />
          Jetzt ausführen
        </Button>
      </div>

      <Alert v-if="error" variant="destructive" class="mb-4">
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>

      <Tabs default-value="config">
        <TabsList class="w-full">
          <TabsTrigger value="config" class="flex-1">
            Konfiguration
          </TabsTrigger>
          <TabsTrigger value="runs" class="flex-1">
            Läufe ({{ runs.length }})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="config" class="mt-4">
          <AutomationForm
            :initial="automation"
            :busy="saving"
            submit-label="Änderungen speichern"
            @submit="onSubmit"
            @cancel="navigateTo('/automations')"
          />
        </TabsContent>

        <TabsContent value="runs" class="mt-4">
          <Card v-if="runs.length === 0" class="py-12 text-center">
            <CardContent>
              <p class="text-sm text-muted-foreground">
                Noch keine Läufe. Klick auf „Jetzt ausführen", um zu starten.
              </p>
            </CardContent>
          </Card>

          <div v-else class="space-y-2">
            <NuxtLink
              v-for="run in runs"
              :key="run.id"
              :to="`/automations/${id}/runs/${run.id}`"
              class="block"
            >
              <Card class="transition-colors hover:border-foreground/20 cursor-pointer">
                <CardContent class="p-3 flex items-center gap-3">
                  <component
                    :is="statusMeta(run.status).icon"
                    :class="['h-4 w-4 shrink-0', statusMeta(run.status).classes]"
                  />
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium">
                        {{ statusMeta(run.status).label }}
                      </span>
                      <Badge variant="outline" class="text-xs font-normal">
                        {{ run.trigger === "schedule" ? "Zeitplan" : "Manuell" }}
                      </Badge>
                      <span v-if="run.email_sent" class="text-xs text-muted-foreground">
                        · E-Mail versendet
                      </span>
                    </div>
                    <div class="text-xs text-muted-foreground mt-0.5">
                      {{ formatDate(run.started_at) }}
                      <span v-if="run.step_results.length">
                        · {{ run.step_results.length }}
                        {{ run.step_results.length === 1 ? "Schritt" : "Schritte" }}
                      </span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </NuxtLink>
          </div>
        </TabsContent>
      </Tabs>
    </template>
  </main>
</template>
