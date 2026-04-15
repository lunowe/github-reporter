<script setup lang="ts">
import { Sun, Moon, Monitor, Check } from "lucide-vue-next";
import type { ThemeMode } from "~/composables/useTheme";

const { mode, setTheme } = useTheme();

const options: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: "system", label: "System", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

/** Icon shown on the trigger button — reflects the current choice. */
const activeIcon = computed(() => {
  const match = options.find((o) => o.value === mode.value);
  return match?.icon ?? Monitor;
});
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button variant="ghost" size="icon" class="h-8 w-8">
        <component :is="activeIcon" class="h-4 w-4" />
        <span class="sr-only">Theme wechseln</span>
      </Button>
    </DropdownMenuTrigger>

    <DropdownMenuContent align="end" class="w-36">
      <DropdownMenuLabel class="text-xs">Erscheinungsbild</DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuRadioGroup :model-value="mode" @update:model-value="setTheme($event as ThemeMode)">
        <DropdownMenuRadioItem
          v-for="opt in options"
          :key="opt.value"
          :value="opt.value"
          class="gap-2 cursor-pointer"
        >
          <template #indicator-icon>
            <Check class="size-3" />
          </template>
          <component :is="opt.icon" class="h-4 w-4 text-muted-foreground" />
          {{ opt.label }}
        </DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
