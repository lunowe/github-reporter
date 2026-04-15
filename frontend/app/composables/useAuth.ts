/**
 * Authentication composable — manages user session state via GitHub OAuth.
 */

export interface AuthUser {
  id: string;
  github_id: number;
  github_login: string;
  avatar_url: string;
  display_name: string;
  email: string;
}

export function useAuth() {
  const user = useState<AuthUser | null>("authUser", () => null);
  const isLoading = useState<boolean>("authLoading", () => true);
  const isAuthenticated = computed(() => !!user.value);

  const { apiFetch } = useApi();

  async function fetchUser() {
    isLoading.value = true;
    try {
      user.value = await apiFetch<AuthUser>("/api/auth/me");
    } catch {
      user.value = null;
    } finally {
      isLoading.value = false;
    }
  }

  async function logout() {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Ignore — cookie will be cleared by the response
    }
    user.value = null;
    navigateTo("/login");
  }

  return {
    user,
    isLoading,
    isAuthenticated,
    fetchUser,
    logout,
  };
}
