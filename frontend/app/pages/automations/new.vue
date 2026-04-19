<script setup lang="ts">
import { ArrowLeft } from "lucide-vue-next";
import type { AutomationCreatePayload } from "~/types/api";

const { createAutomation } = useAutomations();

const busy = ref(false);
const error = ref<string | null>(null);

async function onSubmit(payload: AutomationCreatePayload) {
  busy.value = true;
  error.value = null;
  try {
    const created = await createAutomation(payload);
    await navigateTo(`/automations/${created.id}`);
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Fehler beim Erstellen";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="mx-auto max-w-3xl px-4 py-8 md:px-6">
    <NuxtLink to="/automations">
      <Button variant="ghost" size="sm" class="mb-3 -ml-2 gap-1">
        <ArrowLeft class="h-4 w-4" />
        Zurück zu Automationen
      </Button>
    </NuxtLink>

    <h1 class="text-2xl font-bold tracking-tight mb-2">Neue Automation</h1>
    <p class="text-sm text-muted-foreground mb-6">
      Definiere eine Kette von Prompts, die nach Zeitplan gegen deine
      Repositories laufen.
    </p>

    <Alert v-if="error" variant="destructive" class="mb-4">
      <AlertDescription>{{ error }}</AlertDescription>
    </Alert>

    <AutomationForm
      :busy="busy"
      submit-label="Automation erstellen"
      @submit="onSubmit"
      @cancel="navigateTo('/automations')"
    />
  </main>
</template>
