<script setup lang="ts">
import { Bot, Headphones, Trash2, Volume2 } from '@lucide/vue';

const emit = defineEmits<{
  clearConversation: [];
}>();

const actions = [
  { label: '语音播报', className: 'ghost', icon: Volume2 },
  { label: '清空对话', className: 'light', icon: Trash2 },
  { label: '人工客服', className: 'primary', icon: Headphones },
];

const handleAction = (label: string) => {
  if (label === '清空对话') {
    emit('clearConversation');
  }
};
</script>

<template>
  <header class="top-bar">
    <div class="brand">
      <div class="brand-logo" aria-hidden="true">
        <Bot :size="24" :stroke-width="2.2" />
      </div>
      <div>
        <h1>智能客服</h1>
        <p>24小时为您服务</p>
      </div>
    </div>

    <div class="top-actions">
      <button
        v-for="action in actions"
        :key="action.label"
        class="top-action"
        :class="action.className"
        type="button"
        @click="handleAction(action.label)"
      >
        <component :is="action.icon" :size="17" :stroke-width="2" aria-hidden="true" />
        <span class="action-label">{{ action.label }}</span>
      </button>
    </div>
  </header>
</template>
