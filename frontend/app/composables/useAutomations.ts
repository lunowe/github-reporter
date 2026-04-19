import type {
  Automation,
  AutomationCreatePayload,
  AutomationRun,
  EmailStatus,
} from "~/types/api";

/**
 * Automations composable — CRUD, manual runs, and run history.
 */
export function useAutomations() {
  const { apiFetch } = useApi();

  const automations = useState<Automation[]>("automations", () => []);
  const loading = ref(false);

  async function fetchAutomations() {
    loading.value = true;
    try {
      automations.value = await apiFetch<Automation[]>("/api/automations");
    } catch (e) {
      console.error("Failed to fetch automations:", e);
    } finally {
      loading.value = false;
    }
  }

  async function getAutomation(id: string): Promise<Automation> {
    return await apiFetch<Automation>(`/api/automations/${id}`);
  }

  async function createAutomation(
    payload: AutomationCreatePayload,
  ): Promise<Automation> {
    const result = await apiFetch<Automation>("/api/automations", {
      method: "POST",
      body: payload,
    });
    automations.value = [result, ...automations.value];
    return result;
  }

  async function updateAutomation(
    id: string,
    payload: Partial<AutomationCreatePayload>,
  ): Promise<Automation> {
    const result = await apiFetch<Automation>(`/api/automations/${id}`, {
      method: "PUT",
      body: payload,
    });
    automations.value = automations.value.map((a) =>
      a.id === id ? result : a,
    );
    return result;
  }

  async function toggleAutomation(
    id: string,
    enabled: boolean,
  ): Promise<Automation> {
    const result = await apiFetch<Automation>(
      `/api/automations/${id}/toggle`,
      {
        method: "PATCH",
        body: { enabled },
      },
    );
    automations.value = automations.value.map((a) =>
      a.id === id ? result : a,
    );
    return result;
  }

  async function deleteAutomation(id: string) {
    await apiFetch(`/api/automations/${id}`, { method: "DELETE" });
    automations.value = automations.value.filter((a) => a.id !== id);
  }

  async function runNow(id: string): Promise<AutomationRun> {
    return await apiFetch<AutomationRun>(`/api/automations/${id}/run`, {
      method: "POST",
    });
  }

  async function listRuns(id: string): Promise<AutomationRun[]> {
    return await apiFetch<AutomationRun[]>(`/api/automations/${id}/runs`);
  }

  async function getRun(
    automationId: string,
    runId: string,
  ): Promise<AutomationRun> {
    return await apiFetch<AutomationRun>(
      `/api/automations/${automationId}/runs/${runId}`,
    );
  }

  async function getEmailStatus(): Promise<EmailStatus> {
    return await apiFetch<EmailStatus>("/api/automations/meta/email-status");
  }

  return {
    automations,
    loading,
    fetchAutomations,
    getAutomation,
    createAutomation,
    updateAutomation,
    toggleAutomation,
    deleteAutomation,
    runNow,
    listRuns,
    getRun,
    getEmailStatus,
  };
}

// ── Cron helpers ───────────────────────────────────────────────────────

export interface CronPreset {
  value: string;
  label: string;
}

export const CRON_PRESETS: CronPreset[] = [
  { value: "", label: "Manuell (kein Zeitplan)" },
  { value: "0 * * * *", label: "Stündlich zur vollen Stunde" },
  { value: "0 9 * * *", label: "Täglich um 09:00" },
  { value: "0 9 * * 1", label: "Wöchentlich (Montag 09:00)" },
  { value: "0 9 * * 1-5", label: "Werktags 09:00 (Mo–Fr)" },
  { value: "0 9 1 * *", label: "Monatlich (1. des Monats, 09:00)" },
  { value: "custom", label: "Eigener Cron-Ausdruck…" },
];

/** Human-readable description for a cron expression (very simple). */
export function describeCron(cron: string | null | undefined): string {
  if (!cron) return "Kein Zeitplan — nur manuelle Ausführung";
  const match = CRON_PRESETS.find((p) => p.value === cron);
  if (match) return match.label;
  return `Cron: ${cron}`;
}

/** Format ISO datetime for compact display. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
