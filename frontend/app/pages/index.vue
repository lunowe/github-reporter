<script setup lang="ts">
import { Loader2 } from "lucide-vue-next";

const { repos, loading, fetchRepos } = useRepos();

onMounted(() => fetchRepos());
</script>

<template>
  <main class="mx-auto max-w-5xl px-4 py-8 md:px-6">
    <div class="mb-8">
      <h1 class="text-2xl font-bold tracking-tight">Dashboard</h1>
      <p class="mt-1 text-sm text-muted-foreground">
        Übersicht aller verbundenen Repositories
      </p>
    </div>

    <!-- GitHub API rate-limit widget — always visible, independent of repos -->
    <div class="mb-6">
      <RateLimitDisplay />
    </div>

    <!-- Loading state -->
    <div v-if="loading && repos.length === 0" class="flex justify-center py-12">
      <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
    </div>

    <!-- Empty state -->
    <Card v-else-if="repos.length === 0" class="py-12 text-center">
      <CardContent>
        <p class="text-sm text-muted-foreground">
          Keine Repositories verbunden.
        </p>
        <NuxtLink to="/settings">
          <Button variant="outline" size="sm" class="mt-3">
            Repository hinzufügen
          </Button>
        </NuxtLink>
      </CardContent>
    </Card>

    <!-- Repo overview cards -->
    <div v-else class="flex flex-col gap-6">
      <RepoOverviewCard
        v-for="repo in repos"
        :key="repo.id"
        :repo="repo.repo_full_name"
        :display-name="repo.display_name"
      />
    </div>
  </main>
</template>
