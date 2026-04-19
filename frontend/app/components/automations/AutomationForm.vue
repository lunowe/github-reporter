<script setup lang="ts">
import {
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown,
  Loader2,
  Info,
  Lightbulb,
  Save,
} from "lucide-vue-next";
import { MODEL_OPTIONS } from "~/constants/models";
import { CRON_PRESETS } from "~/composables/useAutomations";
import type {
  Automation,
  AutomationCreatePayload,
  FinalOutputFormat,
} from "~/types/api";

const props = defineProps<{
  initial?: Automation | null;
  submitLabel?: string;
  busy?: boolean;
}>();

const emit = defineEmits<{
  (e: "submit", payload: AutomationCreatePayload): void;
  (e: "cancel"): void;
}>();

const { repos, fetchRepos } = useRepos();
const { getEmailStatus } = useAutomations();

// reka-ui's <SelectItem> forbids value="" (that's reserved for "no selection").
// Use sentinels to represent the "use default" / "no schedule" options in dropdowns.
const DEFAULT_MODEL = "__default__";
const MANUAL_CRON = "__manual__";

// Re-map CRON_PRESETS so the "no schedule" option has a non-empty value.
const cronPresets = CRON_PRESETS.map((p) => ({
  ...p,
  value: p.value === "" ? MANUAL_CRON : p.value,
}));

const emailConfigured = ref(true);
const emailDefaultTo = ref("");

onMounted(async () => {
  await fetchRepos();
  try {
    const s = await getEmailStatus();
    emailConfigured.value = s.configured;
    emailDefaultTo.value = s.default_to || "";
  } catch {
    emailConfigured.value = false;
  }
});

// Form state (clone from `initial` so we don't mutate the prop)
const name = ref(props.initial?.name ?? "");
const description = ref(props.initial?.description ?? "");
const defaultModel = ref<string>(props.initial?.model || DEFAULT_MODEL);
const steps = ref<{ name: string; prompt: string; repo: string; model: string }[]>(
  props.initial?.steps?.map((s) => ({
    name: s.name,
    prompt: s.prompt,
    repo: s.repo,
    model: s.model || DEFAULT_MODEL,
  })) ?? [
    { name: "Schritt 1", prompt: "", repo: "", model: DEFAULT_MODEL },
  ],
);

// Schedule — map current cron to preset or "custom"
const presetMatches = (cron: string | null | undefined) => {
  if (cron === null || cron === undefined) return MANUAL_CRON;
  return CRON_PRESETS.some((p) => p.value === cron && p.value !== "custom")
    ? cron
    : "custom";
};
const schedulePreset = ref<string>(presetMatches(props.initial?.schedule_cron));
const customCron = ref<string>(
  props.initial?.schedule_cron && schedulePreset.value === "custom"
    ? props.initial.schedule_cron
    : "",
);
const timezone = ref(props.initial?.timezone ?? "Europe/Berlin");

const emailEnabled = ref(props.initial?.email_enabled ?? false);
const emailTo = ref(props.initial?.email_to ?? "");
const enabled = ref(props.initial?.enabled ?? true);

// Final-output formatting. "last_step" (default) keeps legacy behavior
// (just use the last step's output). "merge" concatenates all step outputs,
// "template" renders a user-provided string with {{stepN.output}} refs.
const finalOutputFormat = ref<FinalOutputFormat>(
  props.initial?.final_output_format ?? "last_step",
);
const finalOutputTemplate = ref<string>(
  props.initial?.final_output_template ?? "",
);

const validationError = ref<string | null>(null);

const effectiveCron = computed<string | null>(() => {
  if (schedulePreset.value === MANUAL_CRON) return null;
  if (schedulePreset.value === "custom") {
    return customCron.value.trim() || null;
  }
  return schedulePreset.value;
});

function addStep() {
  steps.value.push({
    name: `Schritt ${steps.value.length + 1}`,
    prompt: "",
    repo: steps.value[steps.value.length - 1]?.repo ?? "",
    model: DEFAULT_MODEL,
  });
}

function removeStep(i: number) {
  if (steps.value.length <= 1) return;
  steps.value.splice(i, 1);
}

function moveStep(i: number, dir: -1 | 1) {
  const j = i + dir;
  if (j < 0 || j >= steps.value.length) return;
  const tmp = steps.value[i];
  steps.value[i] = steps.value[j]!;
  steps.value[j] = tmp!;
}

function insertStepRef(i: number, ref: string) {
  const current = steps.value[i];
  if (!current) return;
  current.prompt = `${current.prompt}${current.prompt.endsWith(" ") || current.prompt.length === 0 ? "" : " "}${ref}`;
}

// Built in script so Vue's template parser doesn't choke on literal `{{ }}`.
function stepRefLabel(n: number): string {
  return "{{step" + n + ".output}}";
}

function insertIntoTemplate(ref: string) {
  const t = finalOutputTemplate.value;
  const sep = !t || t.endsWith(" ") || t.endsWith("\n") ? "" : " ";
  finalOutputTemplate.value = `${t}${sep}${ref}`;
}

// Multiline placeholder kept in JS so Vue's template parser never sees the
// literal `{{ }}` markers (they'd otherwise be scanned as interpolations).
const templatePlaceholder = [
  "z.B.",
  "# Wochenreport",
  "",
  "## Pull Requests",
  stepRefLabel(1),
  "",
  "## Zusammenfassung",
  stepRefLabel(2),
].join("\n");

function validate(): string | null {
  if (!name.value.trim()) return "Name ist erforderlich.";
  if (steps.value.length === 0) return "Mindestens ein Schritt erforderlich.";
  for (let i = 0; i < steps.value.length; i++) {
    const s = steps.value[i]!;
    if (!s.name.trim()) return `Schritt ${i + 1}: Name fehlt.`;
    if (!s.prompt.trim()) return `Schritt ${i + 1}: Prompt fehlt.`;
    if (!s.repo) return `Schritt ${i + 1}: Repository fehlt.`;
  }
  if (schedulePreset.value === "custom") {
    const parts = (customCron.value || "").trim().split(/\s+/);
    if (parts.length !== 5) {
      return "Cron-Ausdruck muss 5 Felder haben (Min Std Tag Monat Wochentag).";
    }
  }
  if (
    finalOutputFormat.value === "template" &&
    !finalOutputTemplate.value.trim()
  ) {
    return "Vorlage für finales Ergebnis darf nicht leer sein.";
  }
  return null;
}

function handleSubmit() {
  const err = validate();
  validationError.value = err;
  if (err) return;

  const unwrapModel = (m: string): string | null =>
    !m || m === DEFAULT_MODEL ? null : m;

  const payload: AutomationCreatePayload = {
    name: name.value.trim(),
    description: description.value.trim(),
    steps: steps.value.map((s) => ({
      name: s.name.trim(),
      prompt: s.prompt,
      repo: s.repo,
      model: unwrapModel(s.model),
    })),
    schedule_cron: effectiveCron.value,
    timezone: timezone.value || "Europe/Berlin",
    enabled: enabled.value,
    email_enabled: emailEnabled.value,
    email_to: emailTo.value.trim() || null,
    model: unwrapModel(defaultModel.value),
    final_output_format: finalOutputFormat.value,
    final_output_template:
      finalOutputFormat.value === "template"
        ? finalOutputTemplate.value
        : null,
  };

  emit("submit", payload);
}
</script>

<template>
  <form class="space-y-6" @submit.prevent="handleSubmit">
    <!-- Basics -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base">Allgemein</CardTitle>
        <CardDescription>
          Gib deiner Automation einen Namen und eine kurze Beschreibung.
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="space-y-1.5">
          <Label for="auto-name">Name</Label>
          <Input
            id="auto-name"
            v-model="name"
            placeholder="z.B. Wöchentlicher Teamreport"
            required
          />
        </div>
        <div class="space-y-1.5">
          <Label for="auto-desc">Beschreibung (optional)</Label>
          <Textarea
            id="auto-desc"
            v-model="description"
            placeholder="Kurzbeschreibung, was diese Automation tut."
            rows="2"
          />
        </div>
        <div class="space-y-1.5">
          <Label for="auto-model">Standard-Modell</Label>
          <Select v-model="defaultModel">
            <SelectTrigger id="auto-model" class="w-full">
              <SelectValue placeholder="Server-Standard verwenden" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem :value="DEFAULT_MODEL">Server-Standard verwenden</SelectItem>
              <SelectItem
                v-for="m in MODEL_OPTIONS"
                :key="m.value"
                :value="m.value"
              >
                {{ m.label }}
              </SelectItem>
            </SelectContent>
          </Select>
          <p class="text-xs text-muted-foreground">
            Kann pro Schritt überschrieben werden.
          </p>
        </div>
      </CardContent>
    </Card>

    <!-- Steps -->
    <Card>
      <CardHeader class="flex flex-row items-start justify-between gap-2">
        <div>
          <CardTitle class="text-base">Schritte</CardTitle>
          <CardDescription class="mt-1">
            Jeder Schritt führt einen Prompt gegen ein Repository aus. Mit
            <code v-pre class="text-xs px-1 rounded bg-muted">{{step1.output}}</code>
            kannst du auf vorherige Ausgaben verweisen.
          </CardDescription>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          class="gap-1.5 shrink-0"
          @click="addStep"
        >
          <Plus class="h-4 w-4" />
          Schritt
        </Button>
      </CardHeader>
      <CardContent class="space-y-4">
        <div
          v-for="(step, i) in steps"
          :key="i"
          class="rounded-lg border p-4 space-y-3 bg-muted/20"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 flex-1 min-w-0">
              <Badge variant="secondary" class="shrink-0">
                Schritt {{ i + 1 }}
              </Badge>
              <Input
                v-model="step.name"
                placeholder="Schrittname"
                class="max-w-sm"
              />
            </div>
            <div class="flex items-center gap-1 shrink-0">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                class="h-7 w-7"
                :disabled="i === 0"
                @click="moveStep(i, -1)"
              >
                <ArrowUp class="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                class="h-7 w-7"
                :disabled="i === steps.length - 1"
                @click="moveStep(i, 1)"
              >
                <ArrowDown class="h-3.5 w-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                class="h-7 w-7 text-muted-foreground hover:text-destructive"
                :disabled="steps.length <= 1"
                @click="removeStep(i)"
              >
                <Trash2 class="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div class="space-y-1.5">
              <Label class="text-xs">Repository</Label>
              <Select v-model="step.repo">
                <SelectTrigger class="w-full">
                  <SelectValue placeholder="Auswählen…" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem
                    v-for="r in repos"
                    :key="r.id"
                    :value="r.repo_full_name"
                  >
                    {{ r.display_name }}
                    <span class="text-muted-foreground text-xs ml-1">
                      {{ r.repo_full_name }}
                    </span>
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div class="space-y-1.5">
              <Label class="text-xs">Modell (optional)</Label>
              <Select v-model="step.model">
                <SelectTrigger class="w-full">
                  <SelectValue placeholder="Automation-Default" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem :value="DEFAULT_MODEL">Automation-Default</SelectItem>
                  <SelectItem
                    v-for="m in MODEL_OPTIONS"
                    :key="m.value"
                    :value="m.value"
                  >
                    {{ m.label }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div class="space-y-1.5">
            <div class="flex items-center justify-between gap-2">
              <Label class="text-xs">Prompt</Label>
              <div v-if="i > 0" class="flex flex-wrap gap-1">
                <Button
                  v-for="n in i"
                  :key="n"
                  type="button"
                  variant="ghost"
                  size="sm"
                  class="h-6 px-2 text-xs gap-1"
                  @click="insertStepRef(i, `{{step${n}.output}}`)"
                >
                  <Lightbulb class="h-3 w-3" />
                  {{ stepRefLabel(n) }}
                </Button>
              </div>
            </div>
            <Textarea
              v-model="step.prompt"
              :placeholder="i === 0
                ? 'z.B. Liste alle Pull Requests von letzter Woche und ordne sie nach Autor.'
                : 'z.B. Fasse {{step1.output}} in 3 Bullet Points zusammen.'"
              rows="4"
              class="font-mono text-sm"
            />
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- Final output -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base">Finales Ergebnis</CardTitle>
        <CardDescription>
          Wie soll das Endergebnis aussehen, das gespeichert und per E-Mail
          versendet wird?
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="space-y-1.5">
          <Label>Format</Label>
          <Select v-model="finalOutputFormat">
            <SelectTrigger class="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="last_step">
                Nur Output des letzten Schritts
              </SelectItem>
              <SelectItem value="merge">
                Alle Schritte zusammenfügen (mit Überschriften)
              </SelectItem>
              <SelectItem value="template">
                Eigene Vorlage mit Platzhaltern
              </SelectItem>
            </SelectContent>
          </Select>
          <p class="text-xs text-muted-foreground">
            <span v-if="finalOutputFormat === 'last_step'">
              Standard — der Output des letzten Schritts wird übernommen.
            </span>
            <span v-else-if="finalOutputFormat === 'merge'">
              Jeder Schritt erhält eine Überschrift und wird mit Trennlinien
              aneinandergereiht. Ein-Klick-Variante.
            </span>
            <span v-else>
              Eigene Vorlage — füge unten Platzhalter ein, um die Outputs
              der Schritte beliebig anzuordnen.
            </span>
          </p>
        </div>

        <div v-if="finalOutputFormat === 'template'" class="space-y-1.5">
          <div class="flex items-center justify-between gap-2 flex-wrap">
            <Label for="final-template" class="text-xs">Vorlage</Label>
            <div v-if="steps.length > 0" class="flex flex-wrap gap-1">
              <Button
                v-for="n in steps.length"
                :key="n"
                type="button"
                variant="ghost"
                size="sm"
                class="h-6 px-2 text-xs gap-1"
                @click="insertIntoTemplate(stepRefLabel(n))"
              >
                <Lightbulb class="h-3 w-3" />
                {{ stepRefLabel(n) }}
              </Button>
            </div>
          </div>
          <Textarea
            id="final-template"
            v-model="finalOutputTemplate"
            :placeholder="templatePlaceholder"
            rows="8"
            class="font-mono text-sm"
          />
          <p class="text-xs text-muted-foreground">
            Nur Text-Substitution — kein zusätzlicher LLM-Call. Markdown wird
            in der UI gerendert.
          </p>
        </div>
      </CardContent>
    </Card>

    <!-- Schedule -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base">Zeitplan</CardTitle>
        <CardDescription>
          Wann soll die Automation automatisch laufen? Sie lässt sich jederzeit
          manuell starten.
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="space-y-1.5">
          <Label>Frequenz</Label>
          <Select v-model="schedulePreset">
            <SelectTrigger class="w-full">
              <SelectValue placeholder="Frequenz wählen" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                v-for="p in cronPresets"
                :key="p.value"
                :value="p.value"
              >
                {{ p.label }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div v-if="schedulePreset === 'custom'" class="space-y-1.5">
          <Label for="custom-cron">Cron-Ausdruck</Label>
          <Input
            id="custom-cron"
            v-model="customCron"
            placeholder="z.B. 0 8 * * 1-5"
            class="font-mono"
          />
          <p class="text-xs text-muted-foreground">
            5 Felder: Minute (0–59) · Stunde (0–23) · Tag (1–31) · Monat (1–12)
            · Wochentag (0–6, 0=So)
          </p>
        </div>

        <div
          v-if="schedulePreset !== MANUAL_CRON"
          class="space-y-1.5"
        >
          <Label for="tz">Zeitzone</Label>
          <Input
            id="tz"
            v-model="timezone"
            placeholder="Europe/Berlin"
          />
        </div>

        <div class="flex items-center justify-between rounded-md border px-3 py-2">
          <div>
            <Label class="text-sm">Automation aktiv</Label>
            <p class="text-xs text-muted-foreground">
              Deaktivierte Automationen laufen nicht nach Zeitplan.
            </p>
          </div>
          <Switch v-model="enabled" />
        </div>
      </CardContent>
    </Card>

    <!-- Email -->
    <Card>
      <CardHeader>
        <CardTitle class="text-base flex items-center gap-2">
          E-Mail-Benachrichtigung
        </CardTitle>
        <CardDescription>
          Bekomme das Ergebnis nach jeder erfolgreichen Ausführung per E-Mail.
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <Alert v-if="!emailConfigured" variant="destructive" class="text-xs">
          <Info class="h-4 w-4" />
          <AlertDescription>
            SMTP ist serverseitig nicht konfiguriert. E-Mails werden nicht
            versendet, auch wenn diese Option aktiviert ist.
          </AlertDescription>
        </Alert>

        <div class="flex items-center justify-between rounded-md border px-3 py-2">
          <Label class="text-sm">E-Mail-Versand aktivieren</Label>
          <Switch v-model="emailEnabled" />
        </div>

        <div v-if="emailEnabled" class="space-y-1.5">
          <Label for="email-to">Empfänger</Label>
          <Input
            id="email-to"
            v-model="emailTo"
            type="email"
            :placeholder="emailDefaultTo || 'name@example.com'"
          />
          <p class="text-xs text-muted-foreground">
            Leer lassen für deine Kontoadresse
            <span v-if="emailDefaultTo"> (<code>{{ emailDefaultTo }}</code>)</span>.
          </p>
        </div>
      </CardContent>
    </Card>

    <Alert v-if="validationError" variant="destructive">
      <AlertDescription>{{ validationError }}</AlertDescription>
    </Alert>

    <div class="flex items-center justify-end gap-2">
      <Button type="button" variant="ghost" @click="emit('cancel')">
        Abbrechen
      </Button>
      <Button type="submit" :disabled="busy" class="gap-1.5">
        <Loader2 v-if="busy" class="h-4 w-4 animate-spin" />
        <Save v-else class="h-4 w-4" />
        {{ submitLabel ?? "Speichern" }}
      </Button>
    </div>
  </form>
</template>
