/**
 * Global auth middleware — redirects unauthenticated users to /login.
 */
export default defineNuxtRouteMiddleware(async (to) => {
  // Skip on server-side (cookies are handled by the browser)
  if (import.meta.server) return;

  // Pages that don't require authentication
  const publicPaths = ["/login", "/auth/callback"];
  if (publicPaths.includes(to.path)) {
    return;
  }

  const { isAuthenticated, isLoading, fetchUser } = useAuth();

  // If we haven't checked auth yet, do it now
  if (isLoading.value && !isAuthenticated.value) {
    await fetchUser();
  }

  // Protect all other routes
  if (!isAuthenticated.value) {
    return navigateTo("/login");
  }
});
