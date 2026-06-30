<script setup lang="ts">
const actions = [
  { label: '语音播报', className: 'ghost', icon: 'volume' },
  { label: '清空对话', className: 'light', icon: 'trash' },
  { label: '人工客服', className: 'primary', icon: 'agent' },
];
</script>

<template>
  <header class="top-bar">
    <div class="brand">
      <div class="brand-logo" aria-hidden="true">
        <span class="robot-face">• •</span>
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
      >
        <span class="icon" :class="`icon-${action.icon}`" aria-hidden="true"></span>
        {{ action.label }}
      </button>
    </div>
  </header>
</template>
