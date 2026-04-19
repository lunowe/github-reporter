<script setup lang="ts">
import {
  KeyRound,
  UserPlus,
  Users,
  Plus,
  Trash2,
  Copy,
  Check,
  Loader2,
  Shield,
  ExternalLink,
  Pencil,
  GitBranch,
  Save,
} from "lucide-vue-next";

const { isAdmin, user } = useAuth();
const { codes, loading: codesLoading, fetchCodes, generateCode, revokeCode } = useAccessCodes();
const { invites, loading: invitesLoading, fetchInvites, createInvite, revokeInvite } = useInvites();
const { repos, fetchRepos } = useRepos();
const { apiFetch } = useApi();

// Redirect non-admin users
onMounted(() => {
  if (!isAdmin.value) {
    navigateTo("/");
    return;
  }
  fetchCodes();
  fetchInvites();
  fetchRepos();
  loadUsers();
});

// ── Access Code Generation ──
const codeLabel = ref("");
const codeMaxUses = ref(1);
const codeGenerating = ref(false);
const codeError = ref<string | null>(null);
const generatedCode = ref<string | null>(null);

async function handleGenerateCode() {
  codeGenerating.value = true;
  codeError.value = null;
  generatedCode.value = null;
  try {
    const code = await generateCode(codeLabel.value, codeMaxUses.value);
    generatedCode.value = code.code;
    codeLabel.value = "";
    codeMaxUses.value = 1;
  } catch (e: any) {
    codeError.value = e.data?.detail || e.message || "Fehler beim Erstellen";
  } finally {
    codeGenerating.value = false;
  }
}

// ── Invite Creation ──
const inviteEmail = ref("");
const inviteRepoIds = ref<string[]>([]);
const inviteCreating = ref(false);
const inviteError = ref<string | null>(null);
const createdInviteUrl = ref<string | null>(null);

async function handleCreateInvite() {
  inviteCreating.value = true;
  inviteError.value = null;
  createdInviteUrl.value = null;
  try {
    const invite = await createInvite(inviteEmail.value.trim(), inviteRepoIds.value);
    createdInviteUrl.value = invite.invite_url;
    inviteEmail.value = "";
    inviteRepoIds.value = [];
  } catch (e: any) {
    inviteError.value = e.data?.detail || e.message || "Fehler beim Einladen";
  } finally {
    inviteCreating.value = false;
  }
}

// ── Users List ──
interface UserInfo {
  id: string;
  display_name: string;
  github_login: string | null;
  email: string;
  role: string;
  auth_method: string;
  activated: boolean;
  allowed_repo_ids: string[];
  created_at: string;
  last_seen_at: string;
}
const users = ref<UserInfo[]>([]);
const usersLoading = ref(false);

async function loadUsers() {
  usersLoading.value = true;
  try {
    users.value = await apiFetch<UserInfo[]>("/api/admin/users");
  } catch {
    users.value = [];
  } finally {
    usersLoading.value = false;
  }
}

// ── Edit Shared Repos ──
const editingUser = ref<UserInfo | null>(null);
const editRepoIds = ref<string[]>([]);
const editReposSaving = ref(false);
const editReposError = ref<string | null>(null);
const showEditReposDialog = ref(false);

function openEditRepos(u: UserInfo) {
  editingUser.value = u;
  editRepoIds.value = [...(u.allowed_repo_ids || [])];
  editReposError.value = null;
  showEditReposDialog.value = true;
}

async function saveEditRepos() {
  if (!editingUser.value) return;
  editReposSaving.value = true;
  editReposError.value = null;
  try {
    await apiFetch(`/api/admin/users/${editingUser.value.id}/repos`, {
      method: "PUT",
      body: { allowed_repo_ids: editRepoIds.value },
    });
    // Update local state
    const idx = users.value.findIndex((u) => u.id === editingUser.value!.id);
    if (idx !== -1) {
      users.value[idx].allowed_repo_ids = [...editRepoIds.value];
    }
    showEditReposDialog.value = false;
  } catch (e: any) {
    editReposError.value = e.data?.detail || e.message || "Fehler beim Speichern";
  } finally {
    editReposSaving.value = false;
  }
}

// ── Clipboard ──
const copiedId = ref<string | null>(null);

function copyToClipboard(text: string, id: string) {
  navigator.clipboard.writeText(text);
  copiedId.value = id;
  setTimeout(() => {
    copiedId.value = null;
  }, 2000);
}

function formatDate(d: string | Date) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
</script>

<template>
  <main class="mx-auto max-w-4xl px-4 py-8 md:px-6">
    <div class="flex items-center gap-2 mb-6">
      <Shield class="h-6 w-6 text-primary" />
      <h1 class="text-2xl font-bold tracking-tight">Administration</h1>
    </div>

    <Tabs default-value="codes">
      <TabsList class="w-full">
        <TabsTrigger value="codes" class="flex-1">
          <KeyRound class="h-4 w-4 mr-1.5" />
          Zugangscodes
        </TabsTrigger>
        <TabsTrigger value="invites" class="flex-1">
          <UserPlus class="h-4 w-4 mr-1.5" />
          Einladungen
        </TabsTrigger>
        <TabsTrigger value="users" class="flex-1">
          <Users class="h-4 w-4 mr-1.5" />
          Benutzer
        </TabsTrigger>
      </TabsList>

      <!-- ── Access Codes Tab ── -->
      <TabsContent value="codes" class="mt-4 space-y-4">
        <!-- Generate form -->
        <Card>
          <CardHeader>
            <CardTitle class="text-base">Neuen Zugangscode erstellen</CardTitle>
          </CardHeader>
          <CardContent class="space-y-3">
            <div class="flex gap-3">
              <div class="flex-1">
                <Label class="text-xs">Bezeichnung (optional)</Label>
                <Input
                  v-model="codeLabel"
                  placeholder="z.B. Für Max"
                  :disabled="codeGenerating"
                />
              </div>
              <div class="w-32">
                <Label class="text-xs">Max. Nutzungen</Label>
                <Input
                  v-model.number="codeMaxUses"
                  type="number"
                  min="0"
                  placeholder="0 = unbegrenzt"
                  :disabled="codeGenerating"
                />
              </div>
            </div>

            <Button
              class="gap-2"
              :disabled="codeGenerating"
              @click="handleGenerateCode"
            >
              <Loader2 v-if="codeGenerating" class="h-4 w-4 animate-spin" />
              <Plus v-else class="h-4 w-4" />
              Code erstellen
            </Button>

            <!-- Show generated code -->
            <Alert v-if="generatedCode" class="bg-primary/5 border-primary/20">
              <AlertDescription class="flex items-center gap-3">
                <code class="text-lg font-mono font-bold tracking-widest">{{ generatedCode }}</code>
                <Button
                  variant="ghost"
                  size="icon"
                  class="h-8 w-8"
                  @click="copyToClipboard(generatedCode!, 'generated')"
                >
                  <Check v-if="copiedId === 'generated'" class="h-4 w-4 text-green-500" />
                  <Copy v-else class="h-4 w-4" />
                </Button>
              </AlertDescription>
            </Alert>

            <p v-if="codeError" class="text-sm text-destructive">{{ codeError }}</p>
          </CardContent>
        </Card>

        <!-- Codes list -->
        <Card>
          <CardHeader>
            <CardTitle class="text-base">Bestehende Codes</CardTitle>
          </CardHeader>
          <CardContent>
            <div v-if="codesLoading" class="flex justify-center py-8">
              <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
            </div>

            <div v-else-if="codes.length === 0" class="text-sm text-muted-foreground text-center py-8">
              Noch keine Zugangscodes erstellt.
            </div>

            <div v-else class="space-y-2">
              <div
                v-for="code in codes"
                :key="code.id"
                class="flex items-center justify-between rounded-md border px-3 py-2"
                :class="code.revoked ? 'opacity-50' : ''"
              >
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <code class="text-sm font-mono font-medium tracking-wider">{{ code.code }}</code>
                    <Badge v-if="code.revoked" variant="destructive" class="text-xs">Widerrufen</Badge>
                    <Badge v-else-if="code.max_uses > 0 && code.used_count >= code.max_uses" variant="secondary" class="text-xs">Aufgebraucht</Badge>
                    <Badge v-else variant="outline" class="text-xs">Aktiv</Badge>
                  </div>
                  <div class="text-xs text-muted-foreground mt-0.5">
                    <span v-if="code.label">{{ code.label }} · </span>
                    {{ code.used_count }}/{{ code.max_uses === 0 ? '∞' : code.max_uses }} verwendet
                    · {{ formatDate(code.created_at) }}
                  </div>
                </div>
                <div class="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8"
                    @click="copyToClipboard(code.code, code.id)"
                  >
                    <Check v-if="copiedId === code.id" class="h-4 w-4 text-green-500" />
                    <Copy v-else class="h-4 w-4 text-muted-foreground" />
                  </Button>
                  <Button
                    v-if="!code.revoked"
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8 text-muted-foreground hover:text-destructive"
                    @click="revokeCode(code.id)"
                  >
                    <Trash2 class="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- ── Invites Tab ── -->
      <TabsContent value="invites" class="mt-4 space-y-4">
        <!-- Create invite form -->
        <Card>
          <CardHeader>
            <CardTitle class="text-base">Benutzer einladen</CardTitle>
            <CardDescription>
              Eingeladene Benutzer können sich per E-Mail und Passwort anmelden und auf die ausgewählten Repositories zugreifen.
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            <div class="space-y-2">
              <Label class="text-xs">E-Mail-Adresse</Label>
              <Input
                v-model="inviteEmail"
                type="email"
                placeholder="name@beispiel.de"
                :disabled="inviteCreating"
              />
            </div>

            <!-- Repo selection -->
            <div class="space-y-2">
              <Label class="text-xs">Zugriff auf Repositories</Label>
              <div v-if="repos.length === 0" class="text-xs text-muted-foreground">
                Keine Repositories verbunden. Bitte zuerst Repositories in den Einstellungen hinzufügen.
              </div>
              <div v-else class="space-y-1.5 max-h-40 overflow-y-auto">
                <label
                  v-for="repo in repos"
                  :key="repo.id"
                  class="flex items-center gap-2 rounded-md border px-3 py-1.5 cursor-pointer hover:bg-accent text-sm"
                  :class="inviteRepoIds.includes(repo.id) ? 'border-primary bg-primary/5' : ''"
                >
                  <input
                    type="checkbox"
                    :value="repo.id"
                    v-model="inviteRepoIds"
                    class="rounded"
                  />
                  <span>{{ repo.display_name }}</span>
                  <span class="text-xs text-muted-foreground">{{ repo.repo_full_name }}</span>
                </label>
              </div>
            </div>

            <Button
              class="gap-2"
              :disabled="inviteCreating || !inviteEmail.trim() || inviteRepoIds.length === 0"
              @click="handleCreateInvite"
            >
              <Loader2 v-if="inviteCreating" class="h-4 w-4 animate-spin" />
              <UserPlus v-else class="h-4 w-4" />
              Einladung erstellen
            </Button>

            <!-- Show created invite URL -->
            <Alert v-if="createdInviteUrl" class="bg-primary/5 border-primary/20">
              <AlertDescription class="space-y-2">
                <p class="text-sm font-medium">Einladungslink erstellt:</p>
                <div class="flex items-center gap-2">
                  <code class="text-xs break-all flex-1">{{ createdInviteUrl }}</code>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8 shrink-0"
                    @click="copyToClipboard(createdInviteUrl!, 'invite-url')"
                  >
                    <Check v-if="copiedId === 'invite-url'" class="h-4 w-4 text-green-500" />
                    <Copy v-else class="h-4 w-4" />
                  </Button>
                </div>
              </AlertDescription>
            </Alert>

            <p v-if="inviteError" class="text-sm text-destructive">{{ inviteError }}</p>
          </CardContent>
        </Card>

        <!-- Invites list -->
        <Card>
          <CardHeader>
            <CardTitle class="text-base">Bestehende Einladungen</CardTitle>
          </CardHeader>
          <CardContent>
            <div v-if="invitesLoading" class="flex justify-center py-8">
              <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
            </div>

            <div v-else-if="invites.length === 0" class="text-sm text-muted-foreground text-center py-8">
              Noch keine Einladungen erstellt.
            </div>

            <div v-else class="space-y-2">
              <div
                v-for="invite in invites"
                :key="invite.id"
                class="flex items-center justify-between rounded-md border px-3 py-2"
              >
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-medium">{{ invite.email }}</span>
                    <Badge v-if="invite.redeemed" variant="secondary" class="text-xs">Eingelöst</Badge>
                    <Badge v-else-if="new Date(invite.expires_at) < new Date()" variant="destructive" class="text-xs">Abgelaufen</Badge>
                    <Badge v-else variant="outline" class="text-xs">Ausstehend</Badge>
                  </div>
                  <div class="text-xs text-muted-foreground mt-0.5">
                    {{ invite.repo_ids.length }} Repo(s) · Erstellt {{ formatDate(invite.created_at) }}
                    · Läuft ab {{ formatDate(invite.expires_at) }}
                  </div>
                </div>
                <div class="flex items-center gap-1">
                  <Button
                    v-if="!invite.redeemed"
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8"
                    @click="copyToClipboard(invite.invite_url, invite.id)"
                  >
                    <Check v-if="copiedId === invite.id" class="h-4 w-4 text-green-500" />
                    <Copy v-else class="h-4 w-4 text-muted-foreground" />
                  </Button>
                  <Button
                    v-if="!invite.redeemed"
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8 text-muted-foreground hover:text-destructive"
                    @click="revokeInvite(invite.id)"
                  >
                    <Trash2 class="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- ── Users Tab ── -->
      <TabsContent value="users" class="mt-4">
        <Card>
          <CardHeader>
            <CardTitle class="text-base">Registrierte Benutzer</CardTitle>
          </CardHeader>
          <CardContent>
            <div v-if="usersLoading" class="flex justify-center py-8">
              <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
            </div>

            <div v-else-if="users.length === 0" class="text-sm text-muted-foreground text-center py-8">
              Keine Benutzer vorhanden.
            </div>

            <div v-else class="space-y-2">
              <div
                v-for="u in users"
                :key="u.id"
                class="flex items-center justify-between rounded-md border px-3 py-2"
              >
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-medium">{{ u.display_name }}</span>
                    <Badge v-if="u.role === 'viewer'" variant="secondary" class="text-xs">Viewer</Badge>
                    <Badge v-if="u.activated" variant="outline" class="text-xs">Aktiviert</Badge>
                    <Badge v-else variant="destructive" class="text-xs">Nicht aktiviert</Badge>
                    <Badge v-if="u.role === 'viewer'" variant="outline" class="text-xs">
                      <GitBranch class="h-3 w-3 mr-0.5" />
                      {{ (u.allowed_repo_ids || []).length }} Repo(s)
                    </Badge>
                  </div>
                  <div class="text-xs text-muted-foreground mt-0.5">
                    <span v-if="u.github_login">@{{ u.github_login }}</span>
                    <span v-if="u.github_login && u.email"> · </span>
                    <span v-if="u.email">{{ u.email }}</span>
                    · {{ u.auth_method }}
                    · Zuletzt: {{ formatDate(u.last_seen_at) }}
                  </div>
                </div>
                <div v-if="u.role === 'viewer'" class="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8 text-muted-foreground hover:text-primary"
                    title="Repositories bearbeiten"
                    @click="openEditRepos(u)"
                  >
                    <Pencil class="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>

    <!-- ── Edit Shared Repos Dialog ── -->
    <Dialog v-model:open="showEditReposDialog">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Repositories bearbeiten</DialogTitle>
          <DialogDescription>
            Zugriff für <span class="font-medium">{{ editingUser?.display_name }}</span> verwalten.
          </DialogDescription>
        </DialogHeader>

        <div class="space-y-3 py-2">
          <div v-if="repos.length === 0" class="text-sm text-muted-foreground text-center py-4">
            Keine Repositories verbunden. Bitte zuerst Repositories in den Einstellungen hinzufügen.
          </div>
          <div v-else class="space-y-1.5 max-h-60 overflow-y-auto">
            <label
              v-for="repo in repos"
              :key="repo.id"
              class="flex items-center gap-2 rounded-md border px-3 py-2 cursor-pointer hover:bg-accent text-sm"
              :class="editRepoIds.includes(repo.id) ? 'border-primary bg-primary/5' : ''"
            >
              <input
                type="checkbox"
                :value="repo.id"
                v-model="editRepoIds"
                class="rounded"
              />
              <div class="flex-1 min-w-0">
                <span class="font-medium">{{ repo.display_name }}</span>
                <span class="text-xs text-muted-foreground ml-1.5">{{ repo.repo_full_name }}</span>
              </div>
            </label>
          </div>

          <p v-if="editReposError" class="text-sm text-destructive">{{ editReposError }}</p>
        </div>

        <DialogFooter>
          <Button variant="outline" @click="showEditReposDialog = false" :disabled="editReposSaving">
            Abbrechen
          </Button>
          <Button class="gap-2" @click="saveEditRepos" :disabled="editReposSaving">
            <Loader2 v-if="editReposSaving" class="h-4 w-4 animate-spin" />
            <Save v-else class="h-4 w-4" />
            Speichern
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </main>
</template>
