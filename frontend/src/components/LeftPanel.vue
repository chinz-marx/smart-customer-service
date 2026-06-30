<script setup lang="ts">
interface HistoryItem {
  title: string;
  time: string;
  active?: boolean;
}

const histories: HistoryItem[] = [
  { title: '奖励什么时候到账?', time: '10:30', active: true },
  { title: '如何查询我的权益?', time: '昨天' },
  { title: 'ETC活动怎么参与?', time: '昨天' },
  { title: '积分怎么使用?', time: '前天' },
  { title: '账单问题咨询', time: '3天前' },
  { title: '修改手机号', time: '3天前' },
];

const questions = [
  '奖励未到账怎么办?',
  '如何查询我的权益?',
  'ETC优惠活动有哪些?',
  '积分如何获得?',
  '账单如何查询?',
];
</script>

<template>
  <aside class="side-panel left-panel">
    <button class="new-chat" type="button">
      <span aria-hidden="true">+</span>
      新建对话
    </button>

    <section class="panel-section">
      <div class="section-title-row">
        <h2>历史对话</h2>
        <button class="icon-button refresh" type="button" aria-label="刷新历史"></button>
      </div>

      <div class="history-list">
        <button
          v-for="item in histories"
          :key="item.title"
          class="history-item"
          :class="{ active: item.active }"
          type="button"
        >
          <span class="mini-icon calendar" aria-hidden="true"></span>
          <span class="history-title">{{ item.title }}</span>
          <span class="history-time">{{ item.time }}</span>
        </button>
      </div>

      <button class="more-link" type="button">更多历史记录 <span aria-hidden="true">→</span></button>
    </section>

    <section class="panel-section faq-section">
      <div class="section-title-row">
        <h2>常见问题</h2>
        <button class="swap-button" type="button">
          <span class="swap-icon" aria-hidden="true"></span>
          换一换
        </button>
      </div>

      <div class="faq-list">
        <button v-for="question in questions" :key="question" class="faq-item" type="button">
          <span class="search-dot" aria-hidden="true"></span>
          {{ question }}
        </button>
      </div>
    </section>

    <button class="voice-card" type="button">
      <span class="voice-orb" aria-hidden="true"></span>
      <span>
        <strong>语音助手</strong>
        <small>点击开始语音提问</small>
      </span>
    </button>
  </aside>
</template>
