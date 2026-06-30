<script setup lang="ts">
const shortcuts = [
  { label: '查询权益', tone: 'teal', symbol: '↺' },
  { label: '查询订单', tone: 'blue', symbol: '▤' },
  { label: '我的奖励', tone: 'red', symbol: '◆' },
  { label: '活动中心', tone: 'indigo', symbol: '▣' },
  { label: '联系客服', tone: 'purple', symbol: '☎' },
  { label: '常见问题', tone: 'sky', symbol: '?' },
];

const notices = [
  { title: '关于系统升级的通知', date: '2024-05-20' },
  { title: '端午节活动通知', date: '2024-05-18' },
  { title: '积分规则调整公告', date: '2024-05-15' },
];
</script>

<template>
  <aside class="right-rail">
    <section class="info-card user-info">
      <div class="card-title-row">
        <h2>用户信息</h2>
        <button type="button">更多 <span aria-hidden="true">›</span></button>
      </div>
      <div class="phone-line">
        <strong>138****8888</strong>
        <span>已认证</span>
      </div>
      <div class="member-row">
        <span>会员等级：</span>
        <strong><span aria-hidden="true">♛</span> 黄金会员</strong>
      </div>
      <dl class="score-list">
        <div>
          <dt>当前权益值：</dt>
          <dd>520</dd>
        </div>
        <div>
          <dt>可用积分：</dt>
          <dd>1250</dd>
        </div>
      </dl>
      <button class="detail-link" type="button">查看详细信息 <span aria-hidden="true">›</span></button>
    </section>

    <section class="info-card">
      <h2>快捷入口</h2>
      <div class="shortcut-grid">
        <button v-for="item in shortcuts" :key="item.label" type="button" class="shortcut">
          <span :class="['shortcut-icon', item.tone]" aria-hidden="true">{{ item.symbol }}</span>
          <span>{{ item.label }}</span>
        </button>
      </div>
    </section>

    <section class="info-card rating-card">
      <h2>服务评价</h2>
      <p>本次服务是否解决了您的问题?</p>
      <div class="stars" aria-label="五星评价">
        <button v-for="star in 5" :key="star" type="button" aria-label="评价星级">★</button>
      </div>
      <button class="feedback-link" type="button">意见反馈</button>
    </section>

    <section class="info-card">
      <div class="card-title-row">
        <h2>服务公告</h2>
        <button type="button">更多 <span aria-hidden="true">›</span></button>
      </div>
      <div class="notice-list">
        <article v-for="notice in notices" :key="notice.title">
          <h3>{{ notice.title }}</h3>
          <time>{{ notice.date }}</time>
        </article>
      </div>
    </section>
  </aside>
</template>
