/**
 * Proxy the MCP endpoint root itself (/mcp and /mcp/), which the catch-all
 * [...path] route doesn't match. Always targets the backend mount's root
 * (/mcp/) so clients configured with either form work, query string intact.
 */
export default defineEventHandler((event) => {
  const backendUrl =
    process.env.NUXT_BACKEND_URL || "http://localhost:8200";
  const query = event.path.includes("?") ? event.path.slice(event.path.indexOf("?")) : "";
  return proxyRequest(event, `${backendUrl}/mcp/${query}`);
});
