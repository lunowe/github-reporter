<script setup lang="ts">
import { ArrowRight } from "lucide-vue-next";

const emit = defineEmits<{
  ask: [question: string];
}>();

const suggestions = [
  "Was ist der aktuelle Projektstatus?",
  "Welche PRs sind gerade offen?",
  "Zeig mir die Projektstruktur",
  "Wer hat am meisten beigetragen?",
  "Was wurde diese Woche gemacht?",
  "Was hat sich zwischen main und develop geändert?",
];
</script>

<template>
  <div class="flex flex-wrap justify-center gap-2">
    <Button
      v-for="question in suggestions"
      :key="question"
      variant="outline"
      size="sm"
      class="text-xs gap-1.5"
      @click="emit('ask', question)"
    >
      {{ question }}
      <ArrowRight class="h-3 w-3" />
    </Button>
  </div>
</template>
