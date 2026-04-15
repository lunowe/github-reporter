<script setup lang="ts">
import { KeyRound, Loader2, LogOut } from "lucide-vue-next";

definePageMeta({
  layout: false,
});

const { apiFetch } = useApi();
const { user, fetchUser, logout, isActivated } = useAuth();

const code = ref("");
const loading = ref(false);
const error = ref<string | null>(null);

// If already activated, go home
onMounted(() => {
  if (isActivated.value) {
    navigateTo("/");
  }
});

async function redeemCode() {
  if (!code.value.trim()) return;

  loading.value = true;
  error.value = null;

  try {
    await apiFetch("/api/access-codes/redeem", {
      method: "POST",
      body: { code: code.value.trim() },
    });
    await fetchUser();
    navigateTo("/");
  } catch (e: any) {
    error.value = e.data?.detail || e.message || "Fehler beim Einlösen des Codes";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-background px-4">
    <div class="w-full max-w-sm space-y-8 text-center">
      <!-- Icon & title -->
      <div class="space-y-2">
        <div
          class="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10"
        >
          <KeyRound class="h-7 w-7 text-primary" />
        </div>
        <h1 class="text-2xl font-bold tracking-tight">Zugangscode erforderlich</h1>
        <p class="text-sm text-muted-foreground">
          Bitte gib deinen Zugangscode ein, um das Tool zu aktivieren.
        </p>
      </div>

      <!-- Code input -->
      <form class="space-y-4" @submit.prevent="redeemCode">
        <Input
          v-model="code"
          placeholder="XXXX-XXXX-XXXX"
          class="text-center text-lg tracking-widest uppercase"
          :disabled="loading"
          autocomplete="off"
        />

        <Button
          type="submit"
          size="lg"
          class="w-full gap-2"
          :disabled="loading || !code.trim()"
        >
          <Loader2 v-if="loading" class="h-5 w-5 animate-spin" />
          <KeyRound v-else class="h-5 w-5" />
          Aktivieren
        </Button>

        <p v-if="error" class="text-sm text-destructive">{{ error }}</p>
      </form>

      <!-- User info + logout -->
      <div class="space-y-3 pt-2">
        <div v-if="user" class="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <img
            v-if="user.avatar_url"
            :src="user.avatar_url"
            class="h-5 w-5 rounded-full"
          />
          <span>Angemeldet als <strong>{{ user.github_login || user.display_name }}</strong></span>
        </div>
        <Button variant="ghost" size="sm" class="gap-1.5 text-muted-foreground" @click="logout">
          <LogOut class="h-3.5 w-3.5" />
          Abmelden
        </Button>
      </div>
    </div>
  </div>
</template>
