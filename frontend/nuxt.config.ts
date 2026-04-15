import tailwindcss from "@tailwindcss/vite";

// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: "2025-07-15",
  devtools: { enabled: true },
  css: [
    "~/assets/css/tailwind.css",
    "~/assets/css/markdown.css",
    "highlight.js/styles/github-dark.min.css",
  ],

  vite: {
    plugins: [tailwindcss()],
  },

  modules: ["shadcn-nuxt"],
  shadcn: {
    prefix: "",
    componentDir: "@/components/ui",
  },

  components: [
    {
      path: "~/components",
      pathPrefix: false,
    },
  ],

  runtimeConfig: {
    public: {
      apiBase: "",  // empty = same origin; server routes proxy to backend
    },
  },

  // Proxy is handled via server/routes/api/[...path].ts and
  // server/routes/auth/[...path].ts using proxyRequest().
  // This correctly preserves 302 redirects and Set-Cookie headers
  // for the OAuth flow.
});
