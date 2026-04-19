import type { RateLimitInfo } from "~/types/api";

/**
 * GitHub API rate-limit composable.
 *
 * Fetches the user's remaining quota from /api/dashboard/rate-limit.
 * State is shared across components via useState so we only hit the
 * backend once even if the widget is mounted in multiple places.
 *
 * The GitHub /rate_limit endpoint does NOT consume quota itself, so it's
 * safe to poll on an interval.
 */
export function useRateLimit(options: { pollMs?: number } = {}) {
  const { apiFetch } = useApi();

  const info = useState<RateLimitInfo | null>("rateLimit", () => null);
  const loading = useState<boolean>("rateLimitLoading", () => false);
  const error = useState<string | null>("rateLimitError", () => null);
  const lastFetched = useState<number>("rateLimitLastFetched", () => 0);

  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function fetchRateLimit() {
    loading.value = true;
    error.value = null;
    try {
      info.value = await apiFetch<RateLimitInfo>("/api/dashboard/rate-limit");
      lastFetched.value = Date.now();
    } catch (e: any) {
      error.value = e.data?.detail || e.message || "Fehler beim Laden";
    } finally {
      loading.value = false;
    }
  }

  function startPolling(intervalMs: number) {
    stopPolling();
    pollTimer = setInterval(fetchRateLimit, intervalMs);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // Auto-poll if requested
  if (options.pollMs && options.pollMs > 0) {
    onMounted(() => {
      if (!info.value) fetchRateLimit();
      startPolling(options.pollMs!);
    });
    onBeforeUnmount(stopPolling);
  }

  return {
    info,
    loading,
    error,
    lastFetched,
    fetchRateLimit,
    startPolling,
    stopPolling,
  };
}
