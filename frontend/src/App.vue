<script setup lang="ts">
import ChatWorkspace from './components/ChatWorkspace.vue';
import LeftPanel from './components/LeftPanel.vue';
import RightPanel from './components/RightPanel.vue';
import TopBar from './components/TopBar.vue';
</script>

<template>
  <div class="app-shell">
    <TopBar />
    <main class="main-layout">
      <LeftPanel />
      <ChatWorkspace />
      <RightPanel />
    </main>
  </div>
</template>
