<script setup lang="ts">
import { UserPlus, Loader2, AlertCircle } from "lucide-vue-next";

definePageMeta({
  layout: false,
});

const route = useRoute();
const { apiFetch } = useApi();
const { fetchUser } = useAuth();

const token = route.params.token as string;

// State
const validating = ref(true);
const valid = ref(false);
const inviteEmail = ref("");
const validationError = ref<string | null>(null);

const displayName = ref("");
const password = ref("");
const passwordConfirm = ref("");
const submitting = ref(false);
const submitError = ref<string | null>(null);

// Validate token on mount
onMounted(async () => {
  try {
    const data = await apiFetch<{ valid: boolean; email: string }>(
      `/api/invites/validate/${token}`
    );
    valid.value = data.valid;
    inviteEmail.value = data.email;
  } catch (e: any) {
    validationError.value =
      e.data?.detail || "Ungültige oder abgelaufene Einladung.";
  } finally {
    validating.value = false;
  }
});

const passwordsMatch = computed(
  () => password.value === passwordConfirm.value
);

const canSubmit = computed(
  () =>
    password.value.length >= 8 &&
    passwordsMatch.value &&
    !submitting.value
);

async function redeem() {
  if (!canSubmit.value) return;

  submitting.value = true;
  submitError.value = null;

  try {
    await apiFetch("/api/invites/redeem", {
      method: "POST",
      body: {
        token,
        password: password.value,
        display_name: displayName.value.trim(),
      },
    });
    await fetchUser();
    navigateTo("/");
  } catch (e: any) {
    submitError.value =
      e.data?.detail || e.message || "Fehler beim Erstellen des Kontos.";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-background px-4">
    <div class="w-full max-w-sm space-y-8 text-center">
      <!-- Loading -->
      <div v-if="validating" class="space-y-4">
        <Loader2 class="h-8 w-8 animate-spin mx-auto text-muted-foreground" />
        <p class="text-sm text-muted-foreground">Einladung wird überprüft...</p>
      </div>

      <!-- Invalid token -->
      <div v-else-if="!valid" class="space-y-4">
        <div
          class="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-destructive/10"
        >
          <AlertCircle class="h-7 w-7 text-destructive" />
        </div>
        <h1 class="text-2xl font-bold tracking-tight">Ungültige Einladung</h1>
        <p class="text-sm text-muted-foreground">
          {{ validationError || "Diese Einladung ist ungültig oder abgelaufen." }}
        </p>
        <NuxtLink to="/login">
          <Button variant="outline" size="sm">Zur Anmeldung</Button>
        </NuxtLink>
      </div>

      <!-- Valid token — show registration form -->
      <template v-else>
        <div class="space-y-2">
          <div
            class="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10"
          >
            <UserPlus class="h-7 w-7 text-primary" />
          </div>
          <h1 class="text-2xl font-bold tracking-tight">Einladung annehmen</h1>
          <p class="text-sm text-muted-foreground">
            Erstelle dein Konto für <strong>{{ inviteEmail }}</strong>
          </p>
        </div>

        <form class="space-y-4 text-left" @submit.prevent="redeem">
          <div class="space-y-2">
            <Label for="displayName">Anzeigename</Label>
            <Input
              id="displayName"
              v-model="displayName"
              placeholder="Dein Name"
              :disabled="submitting"
            />
          </div>

          <div class="space-y-2">
            <Label for="password">Passwort</Label>
            <Input
              id="password"
              v-model="password"
              type="password"
              placeholder="Mindestens 8 Zeichen"
              :disabled="submitting"
            />
          </div>

          <div class="space-y-2">
            <Label for="passwordConfirm">Passwort bestätigen</Label>
            <Input
              id="passwordConfirm"
              v-model="passwordConfirm"
              type="password"
              placeholder="Passwort wiederholen"
              :disabled="submitting"
            />
            <p
              v-if="passwordConfirm && !passwordsMatch"
              class="text-xs text-destructive"
            >
              Passwörter stimmen nicht überein.
            </p>
          </div>

          <Button
            type="submit"
            size="lg"
            class="w-full gap-2"
            :disabled="!canSubmit"
          >
            <Loader2 v-if="submitting" class="h-5 w-5 animate-spin" />
            <UserPlus v-else class="h-5 w-5" />
            Konto erstellen
          </Button>

          <p v-if="submitError" class="text-sm text-destructive text-center">
            {{ submitError }}
          </p>
        </form>
      </template>
    </div>
  </div>
</template>
