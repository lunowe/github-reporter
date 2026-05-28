<script setup lang="ts">
/**
 * Compact "cost vs monthly budget" quota bar.
 * Green < 70%, yellow < 100%, red when over budget. Unlimited plans show
 * the spend with no bar.
 */
const props = defineProps<{
  cost: number;
  budget: number | null; // null = unlimited
  pctUsed: number | null;
  showLabel?: boolean;
}>();

function formatUsd(n: number): string {
  if (!n) return "$0.00";
  if (n < 0.01) return "$" + n.toFixed(4);
  return "$" + n.toFixed(2);
}

const pct = computed(() => Math.max(0, Math.min(100, props.pctUsed ?? 0)));
const over = computed(() => props.budget != null && props.cost > props.budget);

const barColor = computed(() => {
  if (over.value) return "bg-red-500";
  if (pct.value >= 70) return "bg-yellow-500";
  return "bg-emerald-500";
});
</script>

<template>
  <div class="w-full">
    <div v-if="showLabel" class="flex items-baseline justify-between gap-2 mb-1">
      <span class="text-xs font-medium tabular-nums">{{ formatUsd(cost) }}</span>
      <span class="text-[11px] text-muted-foreground tabular-nums">
        <template v-if="budget != null">/ {{ formatUsd(budget) }}</template>
        <template v-else>unbegrenzt</template>
      </span>
    </div>

    <template v-if="budget != null">
      <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          class="h-full transition-all duration-500"
          :class="barColor"
          :style="{ width: pct + '%' }"
        />
      </div>
      <div v-if="showLabel" class="mt-1 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{{ (pctUsed ?? 0).toFixed(0) }}% verbraucht</span>
        <span v-if="over" class="text-red-500 font-medium">Budget überschritten</span>
      </div>
    </template>
    <div v-else-if="!showLabel" class="text-[11px] text-muted-foreground tabular-nums">
      {{ formatUsd(cost) }} · unbegrenzt
    </div>
  </div>
</template>
