/**
 * Base API client — wraps $fetch with cookie-based session auth.
 */
export function useApi() {
  const config = useRuntimeConfig();
  const apiBase = config.public.apiBase as string;

  async function apiFetch<T>(path: string, options: any = {}): Promise<T> {
    return await $fetch<T>(`${apiBase}${path}`, {
      ...options,
      credentials: "include",
      headers: {
        ...options.headers,
      },
    });
  }

  return { apiBase, apiFetch };
}
