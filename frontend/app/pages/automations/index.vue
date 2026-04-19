<script setup lang="ts">
import {
  Plus,
  Loader2,
  Play,
  Trash2,
  Pencil,
  Clock,
  Mail,
  GitBranch,
  CalendarClock,
  MailX,
  Zap,
} from "lucide-vue-next";
import {
  CRON_PRESETS,
  describeCron,
  formatDate,
} from "~/composables/useAutomations";
import type { Automation } from "~/types/api";

const {
  automations,
  loading,
  fetchAutomations,
  toggleAutomation,
  deleteAutomation,
  runNow,
  getEmailStatus,
} = useAutomations();

const emailConfigured = ref(true);
const runningId = ref<string | null>(null);
const toDelete = ref<Automation | null>(null);
const deleteLoading = ref(false);
const errorMsg = ref<string | null>(null);

onMounted(async () => {
  await fetchAutomations();
  try {
    const status = await getEmailStatus();
    emailConfigured.value = status.configured;
  } catch {
    emailConfigured.value = false;
  }
});

async function handleToggle(a: Automation, enabled: boolean) {
  try {
    await toggleAutomation(a.id, enabled);
  } catch (e: any) {
    errorMsg.value = e.data?.detail || e.message || "Fehler beim Umschalten";
  }
}

async function handleRunNow(a: Automation) {
  runningId.value = a.id;
  errorMsg.value = null;
  try {
    const run = await runNow(a.id);
    await navigateTo(`/automations/${a.id}/runs/${run.id}`);
  } catch (e: any) {
    errorMsg.value = e.data?.detail || e.message || "Start fehlgeschlagen";
  } finally {
    runningId.value = null;
  }
}

async function confirmDelete() {
  if (!toDelete.value) return;
  deleteLoading.value = true;
  try {
    await deleteAutomation(toDelete.value.id);
    toDelete.value = null;
  } catch (e: any) {
    errorMsg.value = e.data?.detail || e.message || "Löschen fehlgeschlagen";
  } finally {
    deleteLoading.value = false;
  }
}
</script>

<template>
  <main class="mx-auto max-w-5xl px-4 py-8 md:px-6">
    <div class="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold tracking-tight flex items-center gap-2">
          <Zap class="h-6 w-6" />
          Automationen
        </h1>
        <p class="mt-1 text-sm text-muted-foreground">
          Definierte Prompt-Ketten, die nach Zeitplan laufen. Ergebnisse werden
          gespeichert und optional per E-Mail versendet.
        </p>
      </div>
      <NuxtLink to="/automations/new">
        <Button class="gap-1.5">
          <Plus class="h-4 w-4" />
          Neue Automation
        </Button>
      </NuxtLink>
    </div>

    <Alert v-if="errorMsg" variant="destructive" class="mb-4">
      <AlertDescription>{{ errorMsg }}</AlertDescription>
    </Alert>

    <Alert v-if="!emailConfigured" class="mb-4">
      <MailX class="h-4 w-4" />
      <AlertDescription>
        SMTP ist nicht konfiguriert. E-Mail-Benachrichtigungen werden nicht
        versendet, bis der Server mit <code>SMTP_HOST</code> und
        <code>SMTP_FROM</code> konfiguriert ist.
      </AlertDescription>
    </Alert>

    <!-- Loading -->
    <div
      v-if="loading && automations.length === 0"
      class="flex justify-center py-12"
    >
      <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
    </div>

    <!-- Empty -->
    <Card v-else-if="automations.length === 0" class="py-16 text-center">
      <CardContent class="space-y-3">
        <Zap class="h-8 w-8 mx-auto text-muted-foreground" />
        <p class="text-sm text-muted-foreground">
          Noch keine Automationen angelegt.
        </p>
        <NuxtLink to="/automations/new">
          <Button variant="outline" size="sm" class="gap-1.5">
            <Plus class="h-4 w-4" />
            Erste Automation erstellen
          </Button>
        </NuxtLink>
      </CardContent>
    </Card>

    <!-- List -->
    <div v-else class="space-y-3">
      <Card
        v-for="a in automations"
        :key="a.id"
        class="transition-colors hover:border-foreground/20"
      >
        <CardContent class="p-4 md:p-5">
          <div class="flex items-start justify-between gap-4">
            <!-- Title + description -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <NuxtLink
                  :to="`/automations/${a.id}`"
                  class="font-semibold text-base hover:underline truncate"
                >
                  {{ a.name }}
                </NuxtLink>
                <Badge
                  :variant="a.enabled ? 'default' : 'secondary'"
                  class="text-xs"
                >
                  {{ a.enabled ? "Aktiv" : "Pausiert" }}
                </Badge>
                <Badge variant="outline" class="text-xs">
                  {{ a.steps.length }}
                  {{ a.steps.length === 1 ? "Schritt" : "Schritte" }}
                </Badge>
              </div>

              <p
                v-if="a.description"
                class="mt-1 text-sm text-muted-foreground line-clamp-2"
              >
                {{ a.description }}
              </p>

              <div
                class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground"
              >
                <span class="inline-flex items-center gap-1">
                  <CalendarClock class="h-3.5 w-3.5" />
                  {{ describeCron(a.schedule_cron) }}
                </span>
                <span
                  v-if="a.next_run_at && a.enabled"
                  class="inline-flex items-center gap-1"
                >
                  <Clock class="h-3.5 w-3.5" />
                  Nächster Lauf: {{ formatDate(a.next_run_at) }}
                </span>
                <span
                  v-if="a.last_run_at"
                  class="inline-flex items-center gap-1"
                >
                  Letzter Lauf: {{ formatDate(a.last_run_at) }}
                </span>
                <span
                  v-if="a.email_enabled"
                  class="inline-flex items-center gap-1"
                >
                  <Mail class="h-3.5 w-3.5" />
                  E-Mail aktiv
                </span>
              </div>

              <!-- Step repos -->
              <div class="mt-2 flex flex-wrap gap-1.5">
                <Badge
                  v-for="(step, i) in a.steps"
                  :key="i"
                  variant="outline"
                  class="font-normal gap-1 text-xs"
                >
                  <GitBranch class="h-3 w-3" />
                  {{ step.repo }}
                </Badge>
              </div>
            </div>

            <!-- Actions -->
            <div class="flex items-center gap-2 shrink-0">
              <Switch
                :model-value="a.enabled"
                @update:model-value="(v) => handleToggle(a, Boolean(v))"
              />

              <Button
                variant="outline"
                size="sm"
                class="gap-1.5"
                :disabled="runningId === a.id"
                @click="handleRunNow(a)"
              >
                <Loader2
                  v-if="runningId === a.id"
                  class="h-3.5 w-3.5 animate-spin"
                />
                <Play v-else class="h-3.5 w-3.5" />
                <span class="hidden sm:inline">Jetzt ausführen</span>
              </Button>

              <NuxtLink :to="`/automations/${a.id}`">
                <Button variant="ghost" size="icon" class="h-8 w-8">
                  <Pencil class="h-3.5 w-3.5" />
                </Button>
              </NuxtLink>

              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive"
                @click="toDelete = a"
              >
                <Trash2 class="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- Delete confirm -->
    <AlertDialog :open="!!toDelete" @update:open="(o) => !o && (toDelete = null)">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Automation löschen?</AlertDialogTitle>
          <AlertDialogDescription>
            <span v-if="toDelete">
              „{{ toDelete.name }}" wird dauerhaft gelöscht. Alle gespeicherten
              Läufe gehen verloren.
            </span>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel :disabled="deleteLoading">Abbrechen</AlertDialogCancel>
          <AlertDialogAction
            :disabled="deleteLoading"
            class="bg-destructive text-white hover:bg-destructive/90"
            @click="confirmDelete"
          >
            <Loader2 v-if="deleteLoading" class="h-4 w-4 animate-spin mr-1.5" />
            Löschen
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </main>
</template>
