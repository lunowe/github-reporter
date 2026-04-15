<script setup lang="ts">
import { Github, Loader2, Mail } from "lucide-vue-next";

definePageMeta({
  layout: false,
});

const { apiFetch } = useApi();
const { fetchUser } = useAuth();

// ── GitHub login ──
const githubLoading = ref(false);
const githubError = ref<string | null>(null);

async function loginWithGithub() {
  githubLoading.value = true;
  githubError.value = null;
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
    githubError.value = e.data?.detail || e.message || "Fehler beim Anmelden";
    githubLoading.value = false;
  }
}

// ── Email login ──
const email = ref("");
const password = ref("");
const emailLoading = ref(false);
const emailError = ref<string | null>(null);

async function loginWithEmail() {
  if (!email.value.trim() || !password.value) return;

  emailLoading.value = true;
  emailError.value = null;

  try {
    await apiFetch("/api/auth/email/login", {
      method: "POST",
      body: {
        email: email.value.trim(),
        password: password.value,
      },
    });
    await fetchUser();
    navigateTo("/");
  } catch (e: any) {
    emailError.value = e.data?.detail || e.message || "Fehler beim Anmelden";
  } finally {
    emailLoading.value = false;
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

      <!-- GitHub sign in button -->
      <div>
        <Button
          size="lg"
          class="w-full gap-2"
          :disabled="githubLoading"
          @click="loginWithGithub"
        >
          <Loader2 v-if="githubLoading" class="h-5 w-5 animate-spin" />
          <Github v-else class="h-5 w-5" />
          Mit GitHub anmelden
        </Button>

        <p v-if="githubError" class="mt-3 text-sm text-destructive">{{ githubError }}</p>
      </div>

      <!-- Divider -->
      <div class="relative">
        <div class="absolute inset-0 flex items-center">
          <Separator />
        </div>
        <div class="relative flex justify-center text-xs uppercase">
          <span class="bg-background px-2 text-muted-foreground">oder</span>
        </div>
      </div>

      <!-- Email login form -->
      <form class="space-y-3 text-left" @submit.prevent="loginWithEmail">
        <div class="space-y-1.5">
          <Label for="email">E-Mail</Label>
          <Input
            id="email"
            v-model="email"
            type="email"
            placeholder="name@beispiel.de"
            :disabled="emailLoading"
          />
        </div>

        <div class="space-y-1.5">
          <Label for="password">Passwort</Label>
          <Input
            id="password"
            v-model="password"
            type="password"
            placeholder="Passwort"
            :disabled="emailLoading"
          />
        </div>

        <Button
          type="submit"
          variant="outline"
          size="lg"
          class="w-full gap-2"
          :disabled="emailLoading || !email.trim() || !password"
        >
          <Loader2 v-if="emailLoading" class="h-5 w-5 animate-spin" />
          <Mail v-else class="h-5 w-5" />
          Mit E-Mail anmelden
        </Button>

        <p v-if="emailError" class="text-sm text-destructive text-center">{{ emailError }}</p>
      </form>

      <p class="text-xs text-muted-foreground">
        Durch die Anmeldung autorisierst du den Zugriff auf deine
        GitHub-Repositories.
      </p>
    </div>
  </div>
</template>
