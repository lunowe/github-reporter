/**
 * Proxy all /api/* requests to the backend.
 * Ensures cookies (session auth) are forwarded correctly.
 */
export default defineEventHandler((event) => {
  const backendUrl =
    process.env.NUXT_BACKEND_URL || "http://localhost:8200";
  const target = `${backendUrl}${event.path}`;
  return proxyRequest(event, target);
});
