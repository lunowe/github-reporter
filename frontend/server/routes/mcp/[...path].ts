/**
 * Proxy all /mcp/* requests to the backend's mounted MCP server.
 *
 * Lets the MCP endpoint sit behind the same public domain as the app
 * (https://<app>/mcp/) instead of requiring the backend to be exposed
 * directly. Forwards method, headers (incl. Authorization: Bearer ghr_...)
 * and body unchanged. The backend runs the MCP server in stateless JSON mode,
 * so each request is a plain proxied request/response.
 */
export default defineEventHandler((event) => {
  const backendUrl =
    process.env.NUXT_BACKEND_URL || "http://localhost:8200";
  const target = `${backendUrl}${event.path}`;
  return proxyRequest(event, target);
});
