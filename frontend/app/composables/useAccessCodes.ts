/**
 * Access code management composable (admin).
 */

interface AccessCode {
  id: string;
  code: string;
  label: string;
  max_uses: number;
  used_count: number;
  used_by: Array<{ user_id: string; github_login: string; redeemed_at: string }>;
  revoked: boolean;
  created_at: string;
}

export function useAccessCodes() {
  const codes = useState<AccessCode[]>("accessCodes", () => []);
  const loading = useState<boolean>("accessCodesLoading", () => false);

  const { apiFetch } = useApi();

  async function fetchCodes() {
    loading.value = true;
    try {
      codes.value = await apiFetch<AccessCode[]>("/api/access-codes");
    } catch {
      codes.value = [];
    } finally {
      loading.value = false;
    }
  }

  async function generateCode(label: string = "", maxUses: number = 1) {
    const code = await apiFetch<AccessCode>("/api/access-codes", {
      method: "POST",
      body: { label, max_uses: maxUses },
    });
    codes.value.unshift(code);
    return code;
  }

  async function revokeCode(codeId: string) {
    await apiFetch(`/api/access-codes/${codeId}`, { method: "DELETE" });
    const idx = codes.value.findIndex((c) => c.id === codeId);
    if (idx >= 0) {
      codes.value[idx].revoked = true;
    }
  }

  return {
    codes,
    loading,
    fetchCodes,
    generateCode,
    revokeCode,
  };
}
