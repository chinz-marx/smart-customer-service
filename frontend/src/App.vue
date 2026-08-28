<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { PanelLeft } from '@lucide/vue';
import ChatWorkspace from './components/ChatWorkspace.vue';
import KnowledgeAdmin from './components/KnowledgeAdmin.vue';
import LeftPanel from './components/LeftPanel.vue';
import TopBar from './components/TopBar.vue';
import type { ConversationSummary } from './services/conversationApi';
import type { FaqQuestion } from './services/faqApi';

// 当前项目不需要引入完整路由库；hash路由足够隔离客服端和知识后台。
const isKnowledgeAdmin = ref(false);
const chatWorkspaceRef = ref<InstanceType<typeof ChatWorkspace> | null>(null);
const activeConversationId = ref<string | null>(null);
const historyRefreshKey = ref(0);
const isHistoryDrawerOpen = ref(false);
const isMobileLayout = ref(false);

function clearCurrentConversation() {
  if (chatWorkspaceRef.value?.clearConversation()) {
    activeConversationId.value = null;
  }
}

function startNewConversation() {
  if (chatWorkspaceRef.value?.startNewConversation()) {
    activeConversationId.value = null;
    isHistoryDrawerOpen.value = false;
  }
}

async function selectConversation(conversation: ConversationSummary) {
  const opened = await chatWorkspaceRef.value?.openConversation(conversation);
  if (opened) {
    activeConversationId.value = conversation.id;
    isHistoryDrawerOpen.value = false;
  }
}

function handleConversationUpdated(conversationId: string) {
  activeConversationId.value = conversationId;
  historyRefreshKey.value += 1;
}

async function selectFaq(question: FaqQuestion) {
  isHistoryDrawerOpen.value = false;
  await chatWorkspaceRef.value?.answerFaq(question);
}

function handleEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') isHistoryDrawerOpen.value = false;
}

function syncViewport() {
  isMobileLayout.value = window.innerWidth <= 820;
  if (!isMobileLayout.value) isHistoryDrawerOpen.value = false;
}

function syncRoute() {
  isKnowledgeAdmin.value = window.location.hash.startsWith('#/knowledge');
  if (isKnowledgeAdmin.value) isHistoryDrawerOpen.value = false;
}

watch(isHistoryDrawerOpen, (open) => {
  document.body.style.overflow = open ? 'hidden' : '';
});

onMounted(() => {
  syncRoute();
  syncViewport();
  window.addEventListener('hashchange', syncRoute);
  window.addEventListener('keydown', handleEscape);
  window.addEventListener('resize', syncViewport);
});

onBeforeUnmount(() => {
  window.removeEventListener('hashchange', syncRoute);
  window.removeEventListener('keydown', handleEscape);
  window.removeEventListener('resize', syncViewport);
  document.body.style.overflow = '';
});
</script>

<template>
  <KnowledgeAdmin v-if="isKnowledgeAdmin" />
  <div v-else class="app-shell">
    <TopBar @clear-conversation="clearCurrentConversation" />
    <main class="main-layout">
      <button
        v-if="isHistoryDrawerOpen"
        class="history-drawer-backdrop"
        type="button"
        aria-label="关闭历史对话"
        @click="isHistoryDrawerOpen = false"
      ></button>
      <LeftPanel
        :active-conversation-id="activeConversationId"
        :refresh-key="historyRefreshKey"
        :drawer-open="isHistoryDrawerOpen"
        :mobile="isMobileLayout"
        @select-conversation="selectConversation"
        @new-conversation="startNewConversation"
        @close-drawer="isHistoryDrawerOpen = false"
        @select-faq="selectFaq"
      />
      <div class="chat-column">
        <button
          class="mobile-history-trigger"
          type="button"
          aria-controls="conversation-history-drawer"
          :aria-expanded="isHistoryDrawerOpen"
          @click="isHistoryDrawerOpen = true"
        >
          <PanelLeft :size="17" aria-hidden="true" />
          <span class="mobile-history-label">历史对话</span>
        </button>
        <ChatWorkspace
          ref="chatWorkspaceRef"
          @active-conversation-changed="activeConversationId = $event"
          @conversation-updated="handleConversationUpdated"
        />
      </div>
    </main>
  </div>
</template>
