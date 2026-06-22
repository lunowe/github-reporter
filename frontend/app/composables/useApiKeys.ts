/**
 * Personal API key management composable.
 *
 * Keys authenticate against the MCP server (/mcp). The plaintext value is
 * returned only once, at creation time (see `createKey`).
 */

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  revoked: boolean;
  created_at: string | null;
  last_used_at: string | null;
}

export interface CreatedApiKey extends ApiKey {
  key: string; // plaintext — shown once
}

export function useApiKeys() {
  const keys = useState<ApiKey[]>("apiKeys", () => []);
  const loading = useState<boolean>("apiKeysLoading", () => false);

  const { apiFetch } = useApi();

  async function fetchKeys() {
    loading.value = true;
    try {
      keys.value = await apiFetch<ApiKey[]>("/api/api-keys");
    } catch {
      keys.value = [];
    } finally {
      loading.value = false;
    }
  }

  async function createKey(name: string): Promise<CreatedApiKey> {
    const created = await apiFetch<CreatedApiKey>("/api/api-keys", {
      method: "POST",
      body: { name },
    });
    keys.value.unshift({
      id: created.id,
      name: created.name,
      prefix: created.prefix,
      revoked: false,
      created_at: created.created_at,
      last_used_at: null,
    });
    return created;
  }

  async function revokeKey(id: string) {
    await apiFetch(`/api/api-keys/${id}`, { method: "DELETE" });
    const idx = keys.value.findIndex((k) => k.id === id);
    if (idx >= 0) keys.value[idx].revoked = true;
  }

  return { keys, loading, fetchKeys, createKey, revokeKey };
}
