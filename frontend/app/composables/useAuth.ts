/**
 * Authentication composable — manages user session state via GitHub OAuth or email login.
 */

export interface AuthUser {
  id: string;
  github_id: number | null;
  github_login: string | null;
  avatar_url: string;
  display_name: string;
  email: string;
  role: "user" | "viewer";
  activated: boolean;
  auth_method: "github" | "email";
  is_admin: boolean;
  // Plan & usage (productization) — populated by /api/auth/me.
  plan?: string;
  plan_label?: string;
  budget_usd?: number | null;
  extra_usage_opt_in?: boolean;
  usage?: import("~/composables/useAdminStats").UsageSummary | null;
}

export function useAuth() {
  const user = useState<AuthUser | null>("authUser", () => null);
  const isLoading = useState<boolean>("authLoading", () => true);
  const isAuthenticated = computed(() => !!user.value);
  const isActivated = computed(() => user.value?.activated ?? false);
  const isAdmin = computed(() => user.value?.is_admin ?? false);
  const isViewer = computed(() => user.value?.role === "viewer");

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
    isActivated,
    isAdmin,
    isViewer,
    fetchUser,
    logout,
  };
}
