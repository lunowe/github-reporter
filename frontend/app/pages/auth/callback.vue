<script setup lang="ts">
import { Loader2, AlertCircle } from "lucide-vue-next";

definePageMeta({
  layout: false,
});

const { apiFetch } = useApi();
const { fetchUser } = useAuth();

const error = ref<string | null>(null);

onMounted(async () => {
  const route = useRoute();
  const code = route.query.code as string | undefined;
  const state = route.query.state as string | undefined;

  if (!code) {
    error.value = "Kein Autorisierungscode von GitHub erhalten.";
    return;
  }

  // CSRF check: compare state from GitHub with what we stored
  const storedState = sessionStorage.getItem("ghr_oauth_state");
  if (!state || state !== storedState) {
    error.value = "Ungültiger OAuth-State. Bitte erneut versuchen.";
    return;
  }
  sessionStorage.removeItem("ghr_oauth_state");

  try {
    // Exchange code for session via backend
    await apiFetch("/api/auth/github/exchange", {
      method: "POST",
      body: { code },
    });

    // Refresh user state and redirect to home
    await fetchUser();
    navigateTo("/");
  } catch (e: any) {
    error.value =
      e.data?.detail || e.message || "Anmeldung fehlgeschlagen.";
  }
});
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-background px-4">
    <div class="w-full max-w-sm text-center space-y-4">
      <!-- Loading state -->
      <div v-if="!error" class="space-y-3">
        <Loader2 class="mx-auto h-8 w-8 animate-spin text-primary" />
        <p class="text-sm text-muted-foreground">Anmeldung wird abgeschlossen...</p>
      </div>

      <!-- Error state -->
      <div v-else class="space-y-4">
        <AlertCircle class="mx-auto h-8 w-8 text-destructive" />
        <p class="text-sm text-destructive">{{ error }}</p>
        <NuxtLink to="/login">
          <Button variant="outline" size="sm">Zurück zum Login</Button>
        </NuxtLink>
      </div>
    </div>
  </div>
</template>
