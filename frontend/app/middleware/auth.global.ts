/**
 * Global auth middleware — three-tier access control:
 * 1. Public paths: /login, /auth/callback, /invite/*
 * 2. Authenticated but not activated: redirect to /activate
 * 3. Role-based: viewers can't access /settings, non-admins can't access /admin
 */
export default defineNuxtRouteMiddleware(async (to) => {
  // Skip on server-side (cookies are handled by the browser)
  if (import.meta.server) return;

  // Fully public paths — no auth required
  const publicPaths = ["/login", "/auth/callback"];
  if (publicPaths.includes(to.path)) return;

  // Public prefixes (invite redemption pages)
  if (to.path.startsWith("/invite/")) return;

  const { isAuthenticated, isLoading, isActivated, isAdmin, isViewer, fetchUser, user } = useAuth();

  // If we haven't checked auth yet, do it now
  if (isLoading.value && !isAuthenticated.value) {
    await fetchUser();
  }

  // Not logged in at all → login page
  if (!isAuthenticated.value) {
    return navigateTo("/login");
  }

  // Logged in but not activated → activation page (unless already there)
  if (!isActivated.value && to.path !== "/activate") {
    return navigateTo("/activate");
  }

  // Already activated but on /activate → go home
  if (isActivated.value && to.path === "/activate") {
    return navigateTo("/");
  }

  // Admin page → only admins
  if (to.path.startsWith("/admin") && !isAdmin.value) {
    return navigateTo("/");
  }

  // Viewers can't access settings (they can't manage repos)
  if (to.path.startsWith("/settings") && isViewer.value) {
    return navigateTo("/");
  }
});
