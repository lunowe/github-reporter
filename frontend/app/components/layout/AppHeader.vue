<script setup lang="ts">
import { Github, Settings, MessageSquare, LayoutDashboard, Menu, LogOut } from "lucide-vue-next";

// Initialise theme on app load so the .dark class is applied early
useTheme();

const route = useRoute();

const { fetchRepos } = useRepos();
const { user, logout } = useAuth();

const mobileOpen = ref(false);

onMounted(() => fetchRepos());

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/settings", label: "Einstellungen", icon: Settings },
];
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
                :src="user.avatar_url"
                :alt="user.github_login"
                class="h-6 w-6 rounded-full"
              />
              <span class="hidden text-sm sm:inline">{{ user.github_login }}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" class="w-48">
            <DropdownMenuLabel class="font-normal">
              <div class="flex flex-col gap-1">
                <p class="text-sm font-medium">{{ user.display_name }}</p>
                <p class="text-xs text-muted-foreground">@{{ user.github_login }}</p>
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
