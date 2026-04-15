<template>
  <main class="flex h-[calc(100vh-3.5rem)]">
    <!-- Chat history sidebar (desktop) -->
    <aside class="hidden md:flex w-64 border-r flex-col shrink-0">
      <ChatHistory />
    </aside>

    <!-- Main chat area -->
    <div class="flex-1 min-w-0">
      <ChatInterface />
    </div>
  </main>
</template>
