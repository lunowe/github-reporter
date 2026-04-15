<script setup lang="ts">
/**
 * Inline script injected into <head> to apply the saved theme before
 * the first paint — prevents the light-mode flash (FOUC).
 */
useHead({
  script: [
    {
      innerHTML: `(function(){try{var t=localStorage.getItem("github-reporter-theme");var d=t==="dark"||(t!=="light"&&matchMedia("(prefers-color-scheme:dark)").matches);document.documentElement.classList.toggle("dark",d)}catch(e){}})()`,
      tagPosition: "head",
    },
  ],
});
</script>

<template>
  <div class="min-h-screen bg-background font-sans antialiased">
    <AppHeader />
    <NuxtPage />
  </div>
</template>
