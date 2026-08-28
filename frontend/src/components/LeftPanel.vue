<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import {
  ChevronRight,
  History,
  MessageCircle,
  Mic,
  Plus,
  RefreshCw,
  Search,
  Shuffle,
  X,
} from '@lucide/vue';
import {
  listConversations,
  type ConversationSummary,
} from '../services/conversationApi';
import { listFaqQuestions, type FaqQuestion } from '../services/faqApi';

const props = defineProps<{
  activeConversationId: string | null;
  refreshKey: number;
  drawerOpen: boolean;
  mobile: boolean;
}>();

const emit = defineEmits<{
  selectConversation: [conversation: ConversationSummary];
  newConversation: [];
  closeDrawer: [];
  selectFaq: [question: FaqQuestion];
}>();

const PAGE_SIZE = 20;
const MAX_HISTORY = 100;
const histories = ref<ConversationSummary[]>([]);
const historyLimit = ref(PAGE_SIZE);
const isLoading = ref(false);
const isLoadingMore = ref(false);
const errorText = ref('');
const faqQuestions = ref<FaqQuestion[]>([]);
const faqPage = ref(1);
const faqTotal = ref(0);
const faqLoading = ref(false);
const faqError = ref('');
let requestController: AbortController | null = null;

const hasMore = computed(
  () => histories.value.length >= historyLimit.value && historyLimit.value < MAX_HISTORY,
);

const faqTotalPages = computed(() => Math.max(1, Math.ceil(faqTotal.value / 5)));

function relativeTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const diff = Math.max(0, now.getTime() - date.getTime());
  if (diff < 60_000) return '刚刚';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const targetDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDiff = Math.round((today.getTime() - targetDay.getTime()) / 86_400_000);
  if (dayDiff === 0) {
    return new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date);
  }
  if (dayDiff === 1) return '昨天';
  if (dayDiff === 2) return '前天';
  if (dayDiff < 7) return `${dayDiff}天前`;
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(date);
}

async function loadHistory(options: { resetLimit?: boolean; more?: boolean } = {}) {
  if (options.resetLimit) historyLimit.value = PAGE_SIZE;
  requestController?.abort();
  const controller = new AbortController();
  requestController = controller;
  errorText.value = '';
  if (options.more) isLoadingMore.value = true;
  else isLoading.value = true;
  try {
    histories.value = await listConversations(historyLimit.value, controller.signal);
  } catch (error) {
    if (controller.signal.aborted) return;
    errorText.value = error instanceof Error ? error.message : '历史对话加载失败';
  } finally {
    if (requestController === controller) {
      requestController = null;
      isLoading.value = false;
      isLoadingMore.value = false;
    }
  }
}

async function loadMore() {
  if (isLoadingMore.value || !hasMore.value) return;
  const previousLimit = historyLimit.value;
  historyLimit.value = Math.min(historyLimit.value + PAGE_SIZE, MAX_HISTORY);
  await loadHistory({ more: true });
  if (errorText.value) historyLimit.value = previousLimit;
}

async function loadFaq(page = 1) {
  if (faqLoading.value) return;
  faqLoading.value = true;
  faqError.value = '';
  try {
    const result = await listFaqQuestions(page, 5);
    faqQuestions.value = result.records;
    faqPage.value = result.page;
    faqTotal.value = result.total;
  } catch (error) {
    faqError.value = error instanceof Error ? error.message : '常见问题加载失败';
  } finally {
    faqLoading.value = false;
  }
}

function swapFaq() {
  const nextPage = faqPage.value >= faqTotalPages.value ? 1 : faqPage.value + 1;
  void loadFaq(nextPage);
}

watch(
  () => props.refreshKey,
  () => void loadHistory(),
);

onMounted(() => {
  void loadHistory({ resetLimit: true });
  void loadFaq();
});
onBeforeUnmount(() => requestController?.abort());
</script>

<template>
  <aside
    id="conversation-history-drawer"
    class="side-panel left-panel"
    :class="{ 'drawer-open': drawerOpen }"
    :aria-hidden="mobile && !drawerOpen ? 'true' : undefined"
    :inert="mobile && !drawerOpen"
  >
    <div class="history-drawer-heading">
      <strong>对话记录</strong>
      <button type="button" aria-label="关闭历史对话" @click="emit('closeDrawer')">
        <X :size="20" aria-hidden="true" />
      </button>
    </div>

    <button class="new-chat" type="button" @click="emit('newConversation')">
      <Plus :size="19" :stroke-width="2.4" aria-hidden="true" />
      新建对话
    </button>

    <section class="panel-section">
      <div class="section-title-row">
        <h2>历史对话</h2>
        <button
          class="icon-button refresh"
          :class="{ spinning: isLoading }"
          type="button"
          aria-label="刷新历史"
          :disabled="isLoading"
          @click="loadHistory({ resetLimit: true })"
        >
          <RefreshCw :size="16" aria-hidden="true" />
        </button>
      </div>

      <div v-if="isLoading && !histories.length" class="history-state" aria-live="polite">
        <span class="history-loading-dot"></span>
        <span>正在加载历史对话</span>
      </div>

      <div v-else-if="errorText && !histories.length" class="history-state history-error" role="alert">
        <span>{{ errorText }}</span>
        <button type="button" @click="loadHistory({ resetLimit: true })">重新加载</button>
      </div>

      <div v-else-if="!histories.length" class="history-state history-empty">
        <MessageCircle :size="30" :stroke-width="1.6" aria-hidden="true" />
        <strong>暂无历史对话</strong>
        <span>发送第一条消息后会保存在这里</span>
      </div>

      <div v-else class="history-list">
        <button
          v-for="item in histories"
          :key="item.id"
          class="history-item"
          :class="{ active: item.id === activeConversationId }"
          type="button"
          :aria-current="item.id === activeConversationId ? 'true' : undefined"
          @click="emit('selectConversation', item)"
        >
          <History :size="16" :stroke-width="1.8" aria-hidden="true" />
          <span class="history-title">{{ item.title }}</span>
          <span class="history-time">{{ relativeTime(item.updated_at) }}</span>
        </button>
      </div>

      <p v-if="errorText && histories.length" class="history-inline-error" role="alert">
        {{ errorText }}
      </p>
      <button
        v-if="histories.length && hasMore"
        class="more-link"
        type="button"
        :disabled="isLoadingMore"
        @click="loadMore"
      >
        {{ isLoadingMore ? '正在加载…' : '更多历史记录' }}
        <ChevronRight v-if="!isLoadingMore" :size="15" aria-hidden="true" />
      </button>
      <p v-else-if="histories.length" class="history-end">已显示全部对话</p>
    </section>

    <section class="panel-section faq-section">
      <div class="section-title-row">
        <h2>常见问题</h2>
        <button
          class="swap-button"
          type="button"
          :disabled="faqLoading || faqTotal <= 5"
          @click="swapFaq"
        >
          <Shuffle :size="14" aria-hidden="true" />
          换一换
        </button>
      </div>

      <div v-if="faqLoading && !faqQuestions.length" class="faq-state" aria-live="polite">
        正在加载常见问题
      </div>
      <div v-else-if="faqError && !faqQuestions.length" class="faq-state faq-state-error" role="alert">
        <span>{{ faqError }}</span>
        <button type="button" @click="loadFaq(faqPage)">重新加载</button>
      </div>
      <div v-else-if="!faqQuestions.length" class="faq-state">暂无已发布的标准问法</div>
      <div v-else class="faq-list">
        <button
          v-for="question in faqQuestions"
          :key="question.questionId"
          class="faq-item"
          type="button"
          @click="emit('selectFaq', question)"
        >
          <Search :size="16" :stroke-width="1.9" aria-hidden="true" />
          {{ question.questionText }}
        </button>
      </div>
    </section>

    <button class="voice-card" type="button">
      <span class="voice-orb" aria-hidden="true"><Mic :size="19" /></span>
      <span>
        <strong>语音助手</strong>
        <small>点击开始语音提问</small>
      </span>
    </button>
  </aside>
</template>
