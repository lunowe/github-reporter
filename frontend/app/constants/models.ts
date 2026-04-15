/**
 * Shared LLM model definitions used across Settings and ChatInput.
 */

export interface ModelOption {
  value: string;
  label: string;
}

export interface ModelGroup {
  provider: string;
  models: ModelOption[];
}

export const MODEL_GROUPS: ModelGroup[] = [
  {
    provider: "Google",
    models: [
      { value: "gemini-3-flash-preview", label: "Gemini 3 Flash" },
      { value: "gemini-3.1-pro-preview", label: "Gemini 3.1 Pro" },
    ],
  },
  {
    provider: "OpenAI",
    models: [
      { value: "gpt-5.4", label: "GPT-5.4" },
      { value: "gpt-5.4-mini", label: "GPT-5.4 Mini" },
    ],
  },
  {
    provider: "Anthropic",
    models: [
      { value: "claude-sonnet-4.6", label: "Claude Sonnet 4.6" },
    ],
  },
];

/** Flat list of all model options */
export const MODEL_OPTIONS: ModelOption[] = MODEL_GROUPS.flatMap(
  (g) => g.models,
);

/** Look up a display label by model value. Falls back to the raw value. */
export function getModelLabel(value: string): string {
  return MODEL_OPTIONS.find((m) => m.value === value)?.label ?? value;
}

/** Short label for compact display (e.g. dropdown trigger) */
export function getModelShortLabel(value: string): string {
  const label = getModelLabel(value);
  // Already short enough for most cases
  return label;
}
