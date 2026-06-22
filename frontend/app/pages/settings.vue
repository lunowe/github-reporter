<script setup lang="ts">
import {
  Plus,
  Trash2,
  GitBranch,
  Cpu,
  User,
  LogOut,
  ChevronsUpDown,
  Check,
  Lock,
  Loader2,
  ExternalLink,
  KeyRound,
  Copy,
} from "lucide-vue-next";
import { MODEL_OPTIONS } from "~/constants/models";
import type { CreatedApiKey } from "~/composables/useApiKeys";

const {
  repos,
  loading,
  availableRepos,
  availableLoading,
  appInstalled,
  installUrl,
  fetchRepos,
  fetchAvailableRepos,
  addRepo,
  deleteRepo,
} = useRepos();
const { selectedModel } = useChat();
const { user, logout } = useAuth();

// ── API keys / MCP ────────────────────────────────────────────────────
const {
  keys: apiKeys,
  loading: apiKeysLoading,
  fetchKeys,
  createKey,
  revokeKey,
} = useApiKeys();

const newKeyName = ref("");
const creatingKey = ref(false);
const keyError = ref<string | null>(null);
// The plaintext of a just-created key — shown once, then cleared.
const justCreatedKey = ref<CreatedApiKey | null>(null);
const copiedField = ref<string | null>(null);

// MCP endpoint sits behind the same domain as the app (proxied to the backend).
const mcpUrl = ref("");

const mcpConfigSnippet = computed(() => {
  const url = mcpUrl.value || "https://<deine-app>/mcp/";
  const token = justCreatedKey.value?.key || "ghr_DEIN_SCHLÜSSEL";
  return JSON.stringify(
    {
      mcpServers: {
        "github-reporter": {
          type: "http",
          url,
          headers: { Authorization: `Bearer ${token}` },
        },
      },
    },
    null,
    2
  );
});

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

async function copyToClipboard(text: string, field: string) {
  try {
    await navigator.clipboard.writeText(text);
    copiedField.value = field;
    setTimeout(() => {
      if (copiedField.value === field) copiedField.value = null;
    }, 1500);
  } catch {
    /* clipboard unavailable — ignore */
  }
}

async function handleCreateKey() {
  keyError.value = null;
  creatingKey.value = true;
  try {
    justCreatedKey.value = await createKey(newKeyName.value);
    newKeyName.value = "";
  } catch (e: any) {
    keyError.value = e.data?.detail || e.message || "Fehler beim Erstellen";
  } finally {
    creatingKey.value = false;
  }
}

async function handleRevokeKey(id: string) {
  await revokeKey(id);
  if (justCreatedKey.value?.id === id) justCreatedKey.value = null;
}

// Combobox state
const comboboxOpen = ref(false);
const searchQuery = ref("");
const repoError = ref<string | null>(null);
const adding = ref<string | null>(null); // full_name of repo being added

// Connected repo full_names for quick lookup
const connectedSet = computed(
  () => new Set(repos.value.map((r) => r.repo_full_name))
);

// Filter available repos by search query, exclude already connected
const filteredRepos = computed(() => {
  const q = searchQuery.value.toLowerCase();
  return availableRepos.value.filter((r) => {
    if (connectedSet.value.has(r.full_name)) return false;
    if (!q) return true;
    return (
      r.full_name.toLowerCase().includes(q) ||
      r.description.toLowerCase().includes(q)
    );
  });
});

async function handleAddRepo(repo: { full_name: string; default_branch: string }) {
  repoError.value = null;
  adding.value = repo.full_name;
  try {
    await addRepo(repo.full_name, undefined, repo.default_branch);
    // Don't close the popover — let users add multiple repos
  } catch (e: any) {
    repoError.value = e.data?.detail || e.message || "Fehler beim Hinzufügen";
  } finally {
    adding.value = null;
  }
}

// Load repos + API keys on mount; lazy-load available repos when combobox opens
onMounted(() => {
  fetchRepos();
  fetchKeys();
  mcpUrl.value = `${window.location.origin}/mcp/`;
});

watch(comboboxOpen, (open) => {
  if (open && availableRepos.value.length === 0) {
    fetchAvailableRepos();
  }
});
</script>

<template>
  <main class="mx-auto max-w-2xl px-4 py-8 md:px-6">
    <h1 class="text-2xl font-bold tracking-tight mb-6">Einstellungen</h1>

    <Tabs default-value="repos">
      <TabsList class="w-full">
        <TabsTrigger value="repos" class="flex-1">
          <GitBranch class="h-4 w-4 mr-1.5" />
          Repositories
        </TabsTrigger>
        <TabsTrigger value="model" class="flex-1">
          <Cpu class="h-4 w-4 mr-1.5" />
          LLM-Modell
        </TabsTrigger>
        <TabsTrigger value="account" class="flex-1">
          <User class="h-4 w-4 mr-1.5" />
          GitHub-Konto
        </TabsTrigger>
        <TabsTrigger value="mcp" class="flex-1">
          <KeyRound class="h-4 w-4 mr-1.5" />
          API & MCP
        </TabsTrigger>
      </TabsList>

      <!-- Repos tab -->
      <TabsContent value="repos" class="mt-4 space-y-4">
        <Card>
          <CardHeader>
            <CardTitle class="text-base">Verbundene Repositories</CardTitle>
            <CardDescription>
              Verwalte die GitHub-Repositories, die abgefragt werden können.
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            <!-- Existing repos -->
            <div
              v-for="repo in repos"
              :key="repo.id"
              class="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <div>
                <div class="text-sm font-medium">{{ repo.display_name }}</div>
                <div class="text-xs text-muted-foreground">
                  {{ repo.repo_full_name }}
                </div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive"
                @click="deleteRepo(repo.id)"
              >
                <Trash2 class="h-4 w-4" />
              </Button>
            </div>

            <div
              v-if="repos.length === 0 && !loading"
              class="text-sm text-muted-foreground py-4 text-center"
            >
              Keine Repositories verbunden.
            </div>

            <Separator />

            <!-- Add repo — combobox picker -->
            <div class="space-y-2">
              <Label class="text-sm">Repository hinzufügen</Label>

              <Popover v-model:open="comboboxOpen">
                <PopoverTrigger as-child>
                  <Button
                    variant="outline"
                    role="combobox"
                    :aria-expanded="comboboxOpen"
                    class="w-full justify-between text-sm font-normal"
                  >
                    <span class="text-muted-foreground">
                      Repository auswählen...
                    </span>
                    <ChevronsUpDown class="ml-2 h-4 w-4 shrink-0 opacity-50" />
                  </Button>
                </PopoverTrigger>

                <PopoverContent class="w-[--reka-popover-trigger-width] p-0" align="start">
                  <!-- App not installed — show install prompt -->
                  <div v-if="!availableLoading && !appInstalled" class="p-4 space-y-3 text-center">
                    <p class="text-sm text-muted-foreground">
                      Die GitHub App muss auf deinem Konto installiert werden, um auf Repositories zugreifen zu können.
                    </p>
                    <a v-if="installUrl" :href="installUrl" target="_blank">
                      <Button size="sm" class="gap-2">
                        <ExternalLink class="h-4 w-4" />
                        GitHub App installieren
                      </Button>
                    </a>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="ml-2"
                      @click="fetchAvailableRepos()"
                    >
                      Erneut prüfen
                    </Button>
                  </div>

                  <!-- App installed — show searchable repo list -->
                  <Command v-else>
                    <CommandInput
                      v-model="searchQuery"
                      placeholder="Repository suchen..."
                    />
                    <CommandList>
                      <!-- Loading -->
                      <CommandEmpty v-if="availableLoading">
                        <div class="flex items-center justify-center gap-2 py-2">
                          <Loader2 class="h-4 w-4 animate-spin" />
                          <span class="text-sm">Lade Repositories...</span>
                        </div>
                      </CommandEmpty>

                      <!-- No results -->
                      <CommandEmpty v-else>
                        Keine Repositories gefunden.
                      </CommandEmpty>

                      <!-- Repo list -->
                      <CommandGroup v-if="!availableLoading">
                        <CommandItem
                          v-for="repo in filteredRepos"
                          :key="repo.full_name"
                          :value="repo.full_name"
                          class="flex items-center gap-2 cursor-pointer"
                          @select="handleAddRepo(repo)"
                        >
                          <Plus
                            v-if="adding !== repo.full_name"
                            class="h-4 w-4 shrink-0 text-muted-foreground"
                          />
                          <Loader2
                            v-else
                            class="h-4 w-4 shrink-0 animate-spin"
                          />

                          <div class="flex-1 min-w-0">
                            <div class="flex items-center gap-1.5">
                              <span class="text-sm truncate">{{ repo.full_name }}</span>
                              <Lock v-if="repo.private" class="h-3 w-3 shrink-0 text-muted-foreground" />
                            </div>
                            <div
                              v-if="repo.description"
                              class="text-xs text-muted-foreground truncate"
                            >
                              {{ repo.description }}
                            </div>
                          </div>
                        </CommandItem>
                      </CommandGroup>

                      <!-- Manage installation link -->
                      <div v-if="installUrl && !availableLoading" class="border-t px-3 py-2">
                        <a
                          :href="installUrl"
                          target="_blank"
                          class="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                          <ExternalLink class="h-3 w-3" />
                          Repo-Zugriff verwalten
                        </a>
                      </div>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>

              <Alert v-if="repoError" variant="destructive" class="text-xs">
                <AlertDescription>{{ repoError }}</AlertDescription>
              </Alert>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- Model tab -->
      <TabsContent value="model" class="mt-4">
        <Card>
          <CardHeader>
            <CardTitle class="text-base">Standard LLM-Modell</CardTitle>
            <CardDescription>
              Wähle das Standard-Modell für den Agenten.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Select v-model="selectedModel">
              <SelectTrigger class="w-full">
                <SelectValue placeholder="Standard (Gemini 3 Flash)" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="m in MODEL_OPTIONS"
                  :key="m.value"
                  :value="m.value"
                >
                  {{ m.label }}
                </SelectItem>
              </SelectContent>
            </Select>
            <p class="mt-2 text-xs text-muted-foreground">
              Kann pro Chat-Anfrage überschrieben werden.
            </p>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- GitHub Account tab -->
      <TabsContent value="account" class="mt-4">
        <Card>
          <CardHeader>
            <CardTitle class="text-base">GitHub-Konto</CardTitle>
            <CardDescription>
              Dein verbundenes GitHub-Konto wird für den Zugriff auf Repositories verwendet.
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            <div v-if="user" class="flex items-center gap-4">
              <img
                :src="user.avatar_url"
                :alt="user.github_login"
                class="h-12 w-12 rounded-full border"
              />
              <div class="flex-1">
                <div class="font-medium">{{ user.display_name }}</div>
                <div class="text-sm text-muted-foreground">
                  @{{ user.github_login }}
                </div>
                <div v-if="user.email" class="text-xs text-muted-foreground">
                  {{ user.email }}
                </div>
              </div>
              <Badge variant="secondary" class="text-xs">Verbunden</Badge>
            </div>

            <Separator />

            <Button variant="outline" class="gap-2" @click="logout">
              <LogOut class="h-4 w-4" />
              Abmelden
            </Button>
          </CardContent>
        </Card>

        <!-- Usage this month -->
        <Card v-if="user?.usage" class="mt-4">
          <CardHeader>
            <CardTitle class="text-base">Nutzung diesen Monat</CardTitle>
            <CardDescription>
              Tarif <span class="font-medium">{{ user.usage.plan_label }}</span>
              <template v-if="user.usage.budget_usd != null"> · Budget {{ formatUsd(user.usage.budget_usd) }}/Monat</template>
              <template v-else> · unbegrenzt</template>
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-2">
            <AdminUsageBar
              :cost="user.usage.period_cost_usd"
              :budget="user.usage.budget_usd"
              :pct-used="user.usage.pct_used"
              :show-label="true"
            />
            <div class="flex items-center justify-between text-xs text-muted-foreground">
              <span>{{ formatTokens(user.usage.period_tokens) }} Tokens · {{ user.usage.run_count }} Läufe</span>
              <span v-if="user.usage.overage_usd > 0" class="text-red-500">
                Mehrverbrauch: {{ formatUsd(user.usage.overage_usd) }}
              </span>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <!-- API & MCP tab -->
      <TabsContent value="mcp" class="mt-4 space-y-4">
        <!-- API keys -->
        <Card>
          <CardHeader>
            <CardTitle class="text-base">API-Schlüssel</CardTitle>
            <CardDescription>
              Schlüssel authentifizieren MCP-Clients (z.B. Claude Desktop) gegenüber
              diesem Dienst. Sie handeln in deinem Namen – mit deinem GitHub-Zugang
              und deinen Repository-Berechtigungen.
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-4">
            <!-- One-time reveal of a freshly created key -->
            <Alert v-if="justCreatedKey" class="border-primary/40">
              <AlertTitle class="text-sm">Neuer Schlüssel erstellt</AlertTitle>
              <AlertDescription class="space-y-2">
                <p class="text-xs text-muted-foreground">
                  Kopiere ihn jetzt – er wird nur dieses eine Mal angezeigt.
                </p>
                <div class="flex items-center gap-2">
                  <code
                    class="flex-1 truncate rounded bg-muted px-2 py-1.5 font-mono text-xs"
                  >{{ justCreatedKey.key }}</code>
                  <Button
                    variant="outline"
                    size="icon"
                    class="h-8 w-8 shrink-0"
                    @click="copyToClipboard(justCreatedKey.key, 'newkey')"
                  >
                    <Check v-if="copiedField === 'newkey'" class="h-4 w-4 text-green-500" />
                    <Copy v-else class="h-4 w-4" />
                  </Button>
                </div>
              </AlertDescription>
            </Alert>

            <!-- Existing keys -->
            <div
              v-for="key in apiKeys"
              :key="key.id"
              class="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <span class="text-sm font-medium truncate">{{ key.name }}</span>
                  <Badge v-if="key.revoked" variant="destructive" class="text-xs">
                    Widerrufen
                  </Badge>
                </div>
                <div class="text-xs text-muted-foreground font-mono">
                  {{ key.prefix }}…
                </div>
                <div class="text-xs text-muted-foreground">
                  Erstellt {{ formatDate(key.created_at) }} · Zuletzt genutzt
                  {{ formatDate(key.last_used_at) }}
                </div>
              </div>
              <Button
                v-if="!key.revoked"
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive shrink-0"
                @click="handleRevokeKey(key.id)"
              >
                <Trash2 class="h-4 w-4" />
              </Button>
            </div>

            <div
              v-if="apiKeys.length === 0 && !apiKeysLoading"
              class="text-sm text-muted-foreground py-2 text-center"
            >
              Noch keine API-Schlüssel.
            </div>

            <Separator />

            <!-- Create key -->
            <div class="space-y-2">
              <Label class="text-sm">Neuen Schlüssel erstellen</Label>
              <div class="flex items-center gap-2">
                <Input
                  v-model="newKeyName"
                  placeholder="Bezeichnung, z.B. Claude Desktop"
                  class="flex-1"
                  @keyup.enter="handleCreateKey"
                />
                <Button :disabled="creatingKey" class="gap-1.5" @click="handleCreateKey">
                  <Loader2 v-if="creatingKey" class="h-4 w-4 animate-spin" />
                  <Plus v-else class="h-4 w-4" />
                  Erstellen
                </Button>
              </div>
              <Alert v-if="keyError" variant="destructive" class="text-xs">
                <AlertDescription>{{ keyError }}</AlertDescription>
              </Alert>
            </div>
          </CardContent>
        </Card>

        <!-- Integration guide -->
        <Card>
          <CardHeader>
            <CardTitle class="text-base">MCP-Client verbinden</CardTitle>
            <CardDescription>
              In wenigen Schritten einen MCP-fähigen Client (Claude Desktop, Claude.ai,
              Cursor …) mit diesem Dienst verbinden.
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-4 text-sm">
            <!-- Endpoint -->
            <div class="space-y-1.5">
              <Label class="text-xs text-muted-foreground">MCP-Endpunkt (Streamable HTTP)</Label>
              <div class="flex items-center gap-2">
                <code class="flex-1 truncate rounded bg-muted px-2 py-1.5 font-mono text-xs">{{ mcpUrl }}</code>
                <Button
                  variant="outline"
                  size="icon"
                  class="h-8 w-8 shrink-0"
                  @click="copyToClipboard(mcpUrl, 'url')"
                >
                  <Check v-if="copiedField === 'url'" class="h-4 w-4 text-green-500" />
                  <Copy v-else class="h-4 w-4" />
                </Button>
              </div>
            </div>

            <!-- Steps -->
            <ol class="list-decimal space-y-1.5 pl-5 text-muted-foreground">
              <li>Oben einen <span class="font-medium text-foreground">API-Schlüssel</span> erstellen und kopieren.</li>
              <li>Im Client einen <span class="font-medium text-foreground">Remote-MCP-Server (HTTP)</span> hinzufügen.</li>
              <li>Als URL den obigen Endpunkt eintragen (mit Schrägstrich am Ende).</li>
              <li>Den Schlüssel als Header <code class="font-mono text-xs">Authorization: Bearer ghr_…</code> setzen.</li>
              <li>Tools aktualisieren – die GitHub-Reporter-Tools erscheinen. Jeder Tool-Aufruf erwartet einen <code class="font-mono text-xs">repo</code>-Parameter (owner/repo).</li>
            </ol>

            <!-- Claude Desktop config -->
            <div class="space-y-1.5">
              <div class="flex items-center justify-between">
                <Label class="text-xs text-muted-foreground">Beispiel-Konfiguration (Claude Desktop)</Label>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-7 gap-1.5 text-xs"
                  @click="copyToClipboard(mcpConfigSnippet, 'config')"
                >
                  <Check v-if="copiedField === 'config'" class="h-3.5 w-3.5 text-green-500" />
                  <Copy v-else class="h-3.5 w-3.5" />
                  Kopieren
                </Button>
              </div>
              <pre class="overflow-x-auto rounded bg-muted p-3 font-mono text-xs leading-relaxed">{{ mcpConfigSnippet }}</pre>
              <p class="text-xs text-muted-foreground">
                <code class="font-mono">ghr_DEIN_SCHLÜSSEL</code> durch deinen Schlüssel ersetzen.
                Claude.ai: unter „Connectors“ einen eigenen Connector mit obiger URL und
                dem Authorization-Header anlegen.
              </p>
            </div>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  </main>
</template>
