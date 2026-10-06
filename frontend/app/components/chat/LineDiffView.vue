<script setup lang="ts">
import { ChevronDown, ChevronUp } from "lucide-vue-next";
import type { LineDiff } from "~/utils/lineDiff";

/**
 * Unified line diff of an issue body. Folded context unfolds per run; very
 * long diffs are cut after a fixed number of rows with an explicit expand,
 * so the card's buttons stay reachable without scrolling past a wall of text.
 */
const props = defineProps<{ diff: LineDiff }>();

const MAX_ROWS = 40;

const expanded = ref(false);
/** Indices (into diff.rows) of fold rows the user opened. */
const unfolded = ref(new Set<number>());

watch(
  () => props.diff,
  () => {
    unfolded.value = new Set();
    expanded.value = false;
  },
);

type ViewRow =
  | { kind: "ctx" | "add" | "del"; text: string }
  | { kind: "fold"; count: number; index: number };

const rows = computed<ViewRow[]>(() => {
  const out: ViewRow[] = [];
  props.diff.rows.forEach((row, index) => {
    if (row.kind !== "fold") {
      out.push(row);
    } else if (unfolded.value.has(index)) {
      for (const text of row.lines) out.push({ kind: "ctx", text });
    } else {
      out.push({ kind: "fold", count: row.lines.length, index });
    }
  });
  return out;
});

const visible = computed(() =>
  expanded.value ? rows.value : rows.value.slice(0, MAX_ROWS),
);
const hiddenCount = computed(() => rows.value.length - visible.value.length);

function unfold(index: number) {
  const next = new Set(unfolded.value);
  next.add(index);
  unfolded.value = next;
}

const ROW_CLASS = {
  ctx: "text-muted-foreground",
  add: "bg-emerald-500/10 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
  del: "bg-red-500/10 text-red-800 dark:bg-red-500/15 dark:text-red-300",
} as const;

const SIGN = { ctx: "", add: "+", del: "−" } as const;
</script>

<template>
  <p v-if="diff.approximate" class="mb-1.5 text-xs text-muted-foreground">
    Vereinfachte Darstellung – der Text ist zu lang für einen zeilengenauen Vergleich.
  </p>
  <div class="overflow-hidden rounded-md border bg-muted/30">
    <div class="overflow-x-auto">
      <div class="w-max min-w-full py-1 font-mono text-xs leading-5">
        <template v-for="(row, i) in visible" :key="i">
          <button
            v-if="row.kind === 'fold'"
            type="button"
            class="flex w-full items-center gap-1.5 bg-muted/70 px-2 py-0.5 text-left text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
            @click="unfold(row.index)"
          >
            <ChevronDown class="h-3 w-3 shrink-0" />
            <span class="sticky left-7">… {{ row.count }} unveränderte Zeilen …</span>
          </button>
          <div v-else class="flex min-h-5" :class="ROW_CLASS[row.kind]">
            <span class="w-6 shrink-0 select-none text-center opacity-70" aria-hidden="true">
              {{ SIGN[row.kind] }}
            </span>
            <span
              class="whitespace-pre pr-3"
              :class="row.kind === 'del' ? 'line-through decoration-red-500/60' : ''"
              >{{ row.text }}</span
            >
          </div>
        </template>
      </div>
    </div>
    <button
      v-if="hiddenCount > 0 || expanded"
      type="button"
      class="flex w-full items-center justify-center gap-1 border-t bg-muted/40 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <component :is="expanded ? ChevronUp : ChevronDown" class="h-3 w-3" />
      <template v-if="expanded">Weniger anzeigen</template>
      <template v-else-if="hiddenCount === 1">1 weitere Zeile anzeigen</template>
      <template v-else>{{ hiddenCount }} weitere Zeilen anzeigen</template>
    </button>
  </div>
</template>
