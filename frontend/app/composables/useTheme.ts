/**
 * Theme composable — manages light/dark mode with system preference support.
 *
 * Stores the user's choice ("system" | "dark" | "light") in localStorage
 * and applies/removes the `.dark` class on <html> accordingly.
 */

export type ThemeMode = "system" | "dark" | "light";

const STORAGE_KEY = "github-reporter-theme";

export function useTheme() {
  const mode = useState<ThemeMode>("themeMode", () => "system");

  /** Resolved boolean — true when dark mode is active. */
  const isDark = computed(() => {
    if (import.meta.server) return false;
    if (mode.value === "dark") return true;
    if (mode.value === "light") return false;
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  /* ------------------------------------------------------------------ */
  /*  Apply / remove the `.dark` class on <html>                        */
  /* ------------------------------------------------------------------ */
  function applyTheme() {
    if (import.meta.server) return;
    const dark =
      mode.value === "dark" ||
      (mode.value === "system" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);

    document.documentElement.classList.toggle("dark", dark);
  }

  /* ------------------------------------------------------------------ */
  /*  Public setter — persists choice and applies immediately           */
  /* ------------------------------------------------------------------ */
  function setTheme(next: ThemeMode) {
    mode.value = next;
    if (import.meta.server) return;
    localStorage.setItem(STORAGE_KEY, next);
    applyTheme();
  }

  /* ------------------------------------------------------------------ */
  /*  Initialise on mount (client-only)                                 */
  /* ------------------------------------------------------------------ */
  if (import.meta.client) {
    onMounted(() => {
      const stored = localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
      if (stored && ["system", "dark", "light"].includes(stored)) {
        mode.value = stored;
      }
      applyTheme();

      // React to OS-level theme changes when mode is "system"
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const onSystemChange = () => {
        if (mode.value === "system") applyTheme();
      };
      mq.addEventListener("change", onSystemChange);

      // Nuxt will unmount the composable scope on navigation — clean up.
      onUnmounted(() => mq.removeEventListener("change", onSystemChange));
    });
  }

  return {
    /** The raw user choice: "system" | "dark" | "light" */
    mode: readonly(mode),
    /** Whether dark mode is currently active */
    isDark,
    /** Change the theme and persist the choice */
    setTheme,
  };
}
