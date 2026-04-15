/**
 * Invite management composable (admin).
 */

interface Invite {
  id: string;
  email: string;
  token: string;
  invite_url: string;
  invited_by: string;
  repo_ids: string[];
  created_at: string;
  expires_at: string;
  redeemed: boolean;
  redeemed_at: string | null;
}

export function useInvites() {
  const invites = useState<Invite[]>("invites", () => []);
  const loading = useState<boolean>("invitesLoading", () => false);

  const { apiFetch } = useApi();

  async function fetchInvites() {
    loading.value = true;
    try {
      invites.value = await apiFetch<Invite[]>("/api/invites");
    } catch {
      invites.value = [];
    } finally {
      loading.value = false;
    }
  }

  async function createInvite(email: string, repoIds: string[] = []) {
    const invite = await apiFetch<Invite>("/api/invites", {
      method: "POST",
      body: { email, repo_ids: repoIds },
    });
    invites.value.unshift(invite);
    return invite;
  }

  async function revokeInvite(inviteId: string) {
    await apiFetch(`/api/invites/${inviteId}`, { method: "DELETE" });
    invites.value = invites.value.filter((i) => i.id !== inviteId);
  }

  return {
    invites,
    loading,
    fetchInvites,
    createInvite,
    revokeInvite,
  };
}
