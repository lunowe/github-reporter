<script setup lang="ts">
import {
  Send,
  Loader2,
  ChevronDown,
  Sparkles,
  CornerDownLeft,
} from "lucide-vue-next";
import { MODEL_GROUPS, getModelLabel } from "~/constants/models";

const props = defineProps<{
  isStreaming: boolean;
}>();

const emit = defineEmits<{
  send: [query: string];
}>();

const { selectedModel } = useChat();
const input = ref("");
const textareaRef = ref<HTMLTextAreaElement | null>(null);

const currentLabel = computed(() => {
  if (!selectedModel.value) return "Standard-Modell";
  return getModelLabel(selectedModel.value);
});

function resizeTextarea() {
  const el = textareaRef.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 200) + "px";
}

function handleSend() {
  const query = input.value.trim();
  if (!query || props.isStreaming) return;
  emit("send", query);
  input.value = "";
  nextTick(resizeTextarea);
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
}

watch(input, () => nextTick(resizeTextarea));
</script>

<template>
  <div class="bg-background px-4 pb-3 pt-2">
    <div class="mx-auto max-w-3xl">
      <InputGroup
        :data-disabled="isStreaming || undefined"
        class="rounded-xl shadow-sm"
      >
        <!-- Textarea -->
        <textarea
          ref="textareaRef"
          v-model="input"
          data-slot="input-group-control"
          :disabled="isStreaming"
          rows="1"
          class="flex min-h-[44px] max-h-[200px] w-full resize-none overflow-y-auto bg-transparent px-4 py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
          placeholder="Frage zum Projektstatus stellen..."
          @keydown="handleKeydown"
        />

        <!-- Bottom toolbar -->
        <InputGroupAddon align="block-end" class="px-2 py-1.5">
          <!-- Model selector -->
          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <InputGroupButton
                variant="ghost"
                size="sm"
                class="gap-1.5 !px-2.5 text-xs font-normal"
              >
                <Sparkles class="size-3.5 text-primary/70" />
                <span class="max-w-[140px] truncate">{{ currentLabel }}</span>
                <ChevronDown class="size-3 opacity-50" />
              </InputGroupButton>
            </DropdownMenuTrigger>

            <DropdownMenuContent align="start" class="w-56">
              <DropdownMenuLabel>Modell wählen</DropdownMenuLabel>
              <DropdownMenuSeparator />

              <template
                v-for="(group, gIdx) in MODEL_GROUPS"
                :key="group.provider"
              >
                <DropdownMenuSeparator v-if="gIdx > 0" />
                <DropdownMenuLabel
                  class="text-xs font-normal text-muted-foreground"
                >
                  {{ group.provider }}
                </DropdownMenuLabel>
                <DropdownMenuRadioGroup v-model="selectedModel">
                  <DropdownMenuRadioItem
                    v-for="m in group.models"
                    :key="m.value"
                    :value="m.value"
                  >
                    {{ m.label }}
                  </DropdownMenuRadioItem>
                </DropdownMenuRadioGroup>
              </template>
            </DropdownMenuContent>
          </DropdownMenu>

          <!-- Send button -->
          <TooltipProvider :delay-duration="300">
            <Tooltip>
              <TooltipTrigger as-child>
                <InputGroupButton
                  variant="default"
                  size="sm"
                  class="ml-auto"
                  :disabled="!input.trim() || isStreaming"
                  @click="handleSend"
                >
                  <Loader2 v-if="isStreaming" class="size-3.5 animate-spin" />
                  <template v-else>
                    Senden
                    <CornerDownLeft class="size-3.5" />
                  </template>
                </InputGroupButton>
              </TooltipTrigger>
              <TooltipContent side="top">
                <kbd class="text-[10px]">Enter</kbd> zum Senden,
                <kbd class="text-[10px]">Shift + Enter</kbd> für Zeilenumbruch
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </InputGroupAddon>
      </InputGroup>
    </div>
  </div>
</template>
