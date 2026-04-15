<script setup lang="ts">
import { Github, Settings, MessageSquare, LayoutDashboard, Menu, LogOut, Shield, User } from "lucide-vue-next";

// Initialise theme on app load so the .dark class is applied early
useTheme();

const route = useRoute();

const { fetchRepos } = useRepos();
const { user, logout, isAdmin, isViewer } = useAuth();

const mobileOpen = ref(false);

onMounted(() => fetchRepos());

// Build nav items based on role
const navItems = computed(() => {
  const items = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard },
    { to: "/chat", label: "Chat", icon: MessageSquare },
  ];

  // Viewers can't manage repos/settings
  if (!isViewer.value) {
    items.push({ to: "/settings", label: "Einstellungen", icon: Settings });
  }

  // Admin gets admin page
  if (isAdmin.value) {
    items.push({ to: "/admin", label: "Admin", icon: Shield });
  }

  return items;
});
</script>

<template>
  <header
    class="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60"
  >
    <div class="flex h-14 items-center gap-4 px-4 md:px-6">
      <!-- Mobile menu -->
      <Sheet v-model:open="mobileOpen">
        <SheetTrigger as-child>
          <Button variant="ghost" size="icon" class="md:hidden">
            <Menu class="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" class="w-64">
          <SheetHeader>
            <SheetTitle>Navigation</SheetTitle>
            <SheetDescription class="sr-only">Navigation</SheetDescription>
          </SheetHeader>
          <nav class="mt-4 flex flex-col gap-2">
            <NuxtLink
              v-for="item in navItems"
              :key="item.to"
              :to="item.to"
              class="flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
              :class="route.path === item.to ? 'bg-accent font-medium' : ''"
              @click="mobileOpen = false"
            >
              <component :is="item.icon" class="h-4 w-4" />
              {{ item.label }}
            </NuxtLink>
          </nav>
        </SheetContent>
      </Sheet>

      <!-- Logo -->
      <NuxtLink to="/" class="flex items-center gap-2 font-semibold">
        <Github class="h-5 w-5" />
        <span class="hidden sm:inline">GitHub Reporter</span>
      </NuxtLink>

      <!-- Desktop nav -->
      <nav class="hidden items-center gap-1 md:flex">
        <NuxtLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors hover:bg-accent"
          :class="route.path === item.to ? 'bg-accent font-medium' : 'text-muted-foreground'"
        >
          <component :is="item.icon" class="h-4 w-4" />
          {{ item.label }}
        </NuxtLink>
      </nav>

      <!-- Right side: theme toggle + user menu -->
      <div class="ml-auto flex items-center gap-2">
        <ThemeToggle />
      </div>
      <div class="flex items-center gap-2" v-if="user">
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="ghost" size="sm" class="gap-2 px-2">
              <img
                v-if="user.avatar_url"
                :src="user.avatar_url"
                :alt="user.github_login || user.display_name"
                class="h-6 w-6 rounded-full"
              />
              <User v-else class="h-5 w-5 text-muted-foreground" />
              <span class="hidden text-sm sm:inline">{{ user.github_login || user.display_name }}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" class="w-48">
            <DropdownMenuLabel class="font-normal">
              <div class="flex flex-col gap-1">
                <p class="text-sm font-medium">{{ user.display_name }}</p>
                <p v-if="user.github_login" class="text-xs text-muted-foreground">@{{ user.github_login }}</p>
                <p v-else-if="user.email" class="text-xs text-muted-foreground">{{ user.email }}</p>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem @click="logout" class="gap-2 cursor-pointer">
              <LogOut class="h-4 w-4" />
              Abmelden
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  </header>
</template>
