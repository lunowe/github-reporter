<script setup lang="ts">
import { Github, Loader2 } from "lucide-vue-next";

definePageMeta({
  layout: false,
});

const { apiFetch } = useApi();
const loading = ref(false);
const error = ref<string | null>(null);

async function loginWithGithub() {
  loading.value = true;
  error.value = null;
  try {
    const data = await apiFetch<{ url: string; state: string }>(
      "/api/auth/github-url"
    );

    // Store state in sessionStorage for CSRF validation on callback
    if (import.meta.client) {
      sessionStorage.setItem("ghr_oauth_state", data.state);
    }

    // Redirect to GitHub authorize page
    window.location.href = data.url;
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Fehler beim Anmelden";
    loading.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-background px-4">
    <div class="w-full max-w-sm space-y-8 text-center">
      <!-- Logo & title -->
      <div class="space-y-2">
        <div
          class="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10"
        >
          <Github class="h-7 w-7 text-primary" />
        </div>
        <h1 class="text-2xl font-bold tracking-tight">GitHub Reporter</h1>
        <p class="text-sm text-muted-foreground">
          KI-gesteuerte Berichte und Analysen für deine GitHub-Repositories.
        </p>
      </div>

      <!-- Sign in button -->
      <div>
        <Button
          size="lg"
          class="w-full gap-2"
          :disabled="loading"
          @click="loginWithGithub"
        >
          <Loader2 v-if="loading" class="h-5 w-5 animate-spin" />
          <Github v-else class="h-5 w-5" />
          Mit GitHub anmelden
        </Button>

        <p v-if="error" class="mt-3 text-sm text-destructive">{{ error }}</p>
      </div>

      <p class="text-xs text-muted-foreground">
        Durch die Anmeldung autorisierst du den Zugriff auf deine
        GitHub-Repositories.
      </p>
    </div>
  </div>
</template>
