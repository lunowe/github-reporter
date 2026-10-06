<script setup lang="ts">
import { ChevronDown, ChevronUp } from "lucide-vue-next";
import { useResizeObserver } from "@vueuse/core";

/**
 * Clamps tall content (long issue bodies) to a max height with a fade and a
 * "Mehr anzeigen" toggle, so a 20k-character preview doesn't push the card's
 * buttons thousands of pixels down. Content shorter than the limit renders
 * untouched — no toggle, no fade.
 */
const props = withDefaults(defineProps<{ maxHeight?: number }>(), {
  maxHeight: 320,
});

const expanded = ref(false);
const overflows = ref(false);
const inner = ref<HTMLElement | null>(null);

// Small tolerance: don't clamp content that's only a line or two over
function measure() {
  overflows.value = (inner.value?.offsetHeight ?? 0) > props.maxHeight + 32;
}
useResizeObserver(inner, measure);
onMounted(measure);

const clamped = computed(() => overflows.value && !expanded.value);
</script>

<template>
  <div>
    <div
      class="relative"
      :style="clamped ? { maxHeight: `${maxHeight}px`, overflow: 'hidden' } : undefined"
    >
      <div ref="inner"><slot /></div>
      <div
        v-if="clamped"
        class="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-linear-to-t from-card to-transparent"
      />
    </div>
    <button
      v-if="overflows"
      type="button"
      class="mt-1.5 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <component :is="expanded ? ChevronUp : ChevronDown" class="h-3 w-3" />
      {{ expanded ? "Weniger anzeigen" : "Mehr anzeigen" }}
    </button>
  </div>
</template>
