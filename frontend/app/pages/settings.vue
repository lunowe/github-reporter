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
} from "lucide-vue-next";
import { MODEL_OPTIONS } from "~/constants/models";

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

// Load repos on mount; lazy-load available repos when combobox opens
onMounted(() => fetchRepos());

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
      </TabsContent>
    </Tabs>
  </main>
</template>
