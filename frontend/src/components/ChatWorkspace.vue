<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import {
  Bot,
  Keyboard,
  Mic,
  Send,
  Smile,
  UserRound,
} from '@lucide/vue';
import {
  listConversationMessages,
  type ConversationSummary,
} from '../services/conversationApi';
import {
  startFaqAnswerStream,
  type FaqQuestion,
  type FaqStreamDone,
} from '../services/faqApi';

const emit = defineEmits<{
  activeConversationChanged: [conversationId: string | null];
  conversationUpdated: [conversationId: string];
}>();

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  time: string;
  id?: string;
  feedback?: 'helpful' | 'unhelpful';
  streaming?: boolean;
}

interface ChatResponse {
  answer: string;
  session_id: string;
  conversation_id: string | null;
  message_id: string | null;
  ticket_id: string | null;
  provider: string;
  suggestions: string[];
}

type StreamEventName = 'delta' | 'done' | 'error';
type StreamEventPayload = Record<string, unknown>;

const defaultSuggestions = ['奖励未到账怎么办?', '如何查询我的权益?', '活动规则有哪些?'];
const emojis = [
  '😀', '😄', '😊', '🙂', '😉', '😍', '🥰', '😘',
  '😋', '😎', '🤔', '🤗', '😅', '😂', '🥹', '😢',
  '😭', '😤', '😡', '😱', '👍', '👏', '🙏', '💪',
  '👌', '✌️', '❤️', '🎉', '✨', '🔥', '💯', '🌹',
];
const messages = ref<ChatMessage[]>([]);

const inputValue = ref('');
const textareaRef = ref<HTMLTextAreaElement | null>(null);
const emojiPickerRef = ref<HTMLElement | null>(null);
const isEmojiPickerOpen = ref(false);
const isSending = ref(false);
const hasReceivedChunk = ref(false);
const errorText = ref('');
const sessionId = ref<string | null>(null);
const conversationId = ref<string | null>(null);
const suggestions = ref([...defaultSuggestions]);
const conversationRef = ref<HTMLElement | null>(null);
const conversationRating = ref<number | null>(null);
const isRatingSaving = ref(false);
const isHistoryLoading = ref(false);
const isFaqAnswering = ref(false);
const historyLoadError = ref('');
const historyRetryConversation = ref<ConversationSummary | null>(null);
let activeRequestController: AbortController | null = null;
let historyRequestController: AbortController | null = null;
let faqRequestController: AbortController | null = null;

const closeEmojiPicker = () => {
  isEmojiPickerOpen.value = false;
};

const toggleEmojiPicker = () => {
  isEmojiPickerOpen.value = !isEmojiPickerOpen.value;
};

const insertEmoji = async (emoji: string) => {
  const textarea = textareaRef.value;
  const start = textarea?.selectionStart ?? inputValue.value.length;
  const end = textarea?.selectionEnd ?? start;
  inputValue.value = `${inputValue.value.slice(0, start)}${emoji}${inputValue.value.slice(end)}`;
  await nextTick();
  textareaRef.value?.focus();
  const cursorPosition = start + emoji.length;
  textareaRef.value?.setSelectionRange(cursorPosition, cursorPosition);
};

const handleDocumentPointerDown = (event: PointerEvent) => {
  if (
    isEmojiPickerOpen.value
    && event.target instanceof Node
    && !emojiPickerRef.value?.contains(event.target)
  ) {
    closeEmojiPicker();
  }
};

const handleDocumentKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') closeEmojiPicker();
};

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown);
  document.addEventListener('keydown', handleDocumentKeydown);
});

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown);
  document.removeEventListener('keydown', handleDocumentKeydown);
});

// 本次对话评价落在最后一条已持久化的AI回复上，和后端现有反馈表结构保持一致。
const latestAssistantMessage = computed(() =>
  [...messages.value]
    .reverse()
    .find((message) => message.role === 'assistant' && Boolean(message.id)),
);

const resetConversationState = () => {
  historyRequestController?.abort();
  historyRequestController = null;
  faqRequestController?.abort();
  faqRequestController = null;

  const controller = activeRequestController;
  activeRequestController = null;
  controller?.abort();

  messages.value = [];
  inputValue.value = '';
  closeEmojiPicker();
  errorText.value = '';
  historyLoadError.value = '';
  historyRetryConversation.value = null;
  sessionId.value = null;
  conversationId.value = null;
  conversationRating.value = null;
  suggestions.value = [...defaultSuggestions];
  isSending.value = false;
  isHistoryLoading.value = false;
  isFaqAnswering.value = false;
  hasReceivedChunk.value = false;
  emit('activeConversationChanged', null);
};

const clearConversation = () => {
  if (messages.value.length > 0 && !window.confirm('确定清空当前对话吗？清空后将开始一个新会话。')) {
    return false;
  }
  resetConversationState();
  return true;
};

const startNewConversation = () => {
  if (
    isSending.value
    && !window.confirm('当前回答仍在生成，确定中止并新建对话吗？')
  ) {
    return false;
  }
  resetConversationState();
  return true;
};

const messageTime = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return new Intl.DateTimeFormat('zh-CN', {
    ...(sameDay ? {} : { month: 'numeric', day: 'numeric' }),
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
};

const openConversation = async (conversation: ConversationSummary) => {
  if (conversation.id === conversationId.value && messages.value.length) return true;
  if (
    isSending.value
    && !window.confirm('当前回答仍在生成，切换历史对话将中止生成，确定继续吗？')
  ) {
    return false;
  }

  activeRequestController?.abort();
  activeRequestController = null;
  isSending.value = false;
  hasReceivedChunk.value = false;
  faqRequestController?.abort();
  faqRequestController = null;
  isFaqAnswering.value = false;
  historyRequestController?.abort();
  const controller = new AbortController();
  historyRequestController = controller;
  isHistoryLoading.value = true;
  historyLoadError.value = '';
  errorText.value = '';

  try {
    const records = await listConversationMessages(conversation.id, 100, controller.signal);
    messages.value = records
      .filter((item) => item.role === 'user' || item.role === 'assistant')
      .map((item) => ({
        id: item.id,
        role: item.role as 'user' | 'assistant',
        content: item.content,
        time: messageTime(item.created_at),
      }));
    sessionId.value = conversation.session_id;
    conversationId.value = conversation.id;
    conversationRating.value = null;
    suggestions.value = [...defaultSuggestions];
    historyRetryConversation.value = null;
    emit('activeConversationChanged', conversation.id);
    await scrollToBottom();
    return true;
  } catch (error) {
    if (controller.signal.aborted) return false;
    historyLoadError.value = error instanceof Error ? error.message : '历史消息加载失败';
    historyRetryConversation.value = conversation;
    return false;
  } finally {
    if (historyRequestController === controller) {
      historyRequestController = null;
      isHistoryLoading.value = false;
    }
  }
};

const answerFaq = async (question: FaqQuestion) => {
  if (isFaqAnswering.value || isHistoryLoading.value) return false;
  if (
    isSending.value
    && !window.confirm('当前回答仍在生成，确定中止并查看常见问题吗？')
  ) {
    return false;
  }
  activeRequestController?.abort();
  activeRequestController = null;
  isSending.value = false;
  hasReceivedChunk.value = false;
  const controller = new AbortController();
  faqRequestController = controller;
  isFaqAnswering.value = true;
  errorText.value = '';
  const time = currentTime();
  const userMessage: ChatMessage = {
    role: 'user',
    content: question.questionText,
    time,
  };
  const assistantMessage: ChatMessage = {
    role: 'assistant',
    content: '',
    time,
    streaming: true,
  };
  // 问题只在发起请求时插入一次；done事件只回填消息ID，不重复追加内容。
  messages.value.push(userMessage, assistantMessage);
  await scrollToBottom();
  let completed = false;
  try {
    const response = await startFaqAnswerStream(
      question.questionId,
      { sessionId: sessionId.value, conversationId: conversationId.value },
      controller.signal,
    );
    await readSseStream(response, async (event, payload) => {
      if (event === 'delta') {
        const chunk = typeof payload.content === 'string' ? payload.content : '';
        if (chunk) {
          assistantMessage.content += chunk;
          await scrollToBottom();
        }
        return;
      }
      if (event === 'done') {
        const result = payload as unknown as FaqStreamDone;
        userMessage.id = result.userMessageId;
        assistantMessage.id = result.assistantMessageId;
        assistantMessage.time = messageTime(result.createdAt);
        assistantMessage.streaming = false;
        sessionId.value = result.sessionId;
        conversationId.value = result.conversationId;
        completed = true;
        emit('activeConversationChanged', result.conversationId);
        emit('conversationUpdated', result.conversationId);
        return;
      }
      const message = typeof payload.message === 'string' ? payload.message : '常见问题流式回答失败';
      throw new Error(message);
    });
    if (!completed) throw new Error('常见问题流提前结束');
    return true;
  } catch (error) {
    if (controller.signal.aborted) return false;
    assistantMessage.streaming = false;
    if (!assistantMessage.content) {
      assistantMessage.content = '抱歉，常见问题回答暂时不可用，请稍后重试。';
    } else {
      assistantMessage.content += '\n\n连接已中断，请稍后重试。';
    }
    errorText.value = error instanceof Error ? error.message : '常见问题回答失败，请稍后重试。';
    return false;
  } finally {
    if (faqRequestController === controller) {
      faqRequestController = null;
      isFaqAnswering.value = false;
    }
  }
};

defineExpose({ clearConversation, startNewConversation, openConversation, answerFaq });

const currentTime = () =>
  new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date());

const scrollToBottom = async () => {
  await nextTick();
  if (conversationRef.value) {
    conversationRef.value.scrollTop = conversationRef.value.scrollHeight;
  }
};

const readSseStream = async (
  response: Response,
  onEvent: (event: StreamEventName, payload: StreamEventPayload) => void | Promise<void>,
) => {
  if (!response.body) {
    throw new Error('浏览器没有返回可读取的流');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n');

    let separatorIndex = buffer.indexOf('\n\n');
    while (separatorIndex >= 0) {
      const block = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      separatorIndex = buffer.indexOf('\n\n');

      if (!block.trim()) continue;
      const lines = block.split('\n');
      const eventLine = lines.find((line) => line.startsWith('event: '));
      const dataLines = lines.filter((line) => line.startsWith('data: '));
      if (!eventLine || dataLines.length === 0) continue;

      const event = eventLine.slice(7) as StreamEventName;
      const payload = JSON.parse(dataLines.map((line) => line.slice(6)).join('\n')) as StreamEventPayload;
      await onEvent(event, payload);
    }

    if (done) break;
  }
};

const sendMessage = async (preset?: string) => {
  const content = (preset ?? inputValue.value).trim();
  if (!content || isSending.value || isHistoryLoading.value || isFaqAnswering.value) return;

  errorText.value = '';
  inputValue.value = '';
  closeEmojiPicker();
  // 当前问题通过message字段单独发送，history只携带此前对话，避免模型看到重复输入。
  const historyForRequest = messages.value.slice(-10).map((item) => ({
    role: item.role,
    content: item.content,
  }));
  messages.value.push({ role: 'user', content, time: currentTime() });
  isSending.value = true;
  hasReceivedChunk.value = false;
  let assistantMessage: ChatMessage | null = null;
  const requestController = new AbortController();
  activeRequestController = requestController;
  await scrollToBottom();

  const ensureAssistantMessage = () => {
    if (!assistantMessage) {
      assistantMessage = {
        role: 'assistant',
        content: '',
        time: currentTime(),
      };
      messages.value.push(assistantMessage);
      hasReceivedChunk.value = true;
    }
    return assistantMessage;
  };

  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      signal: requestController.signal,
      body: JSON.stringify({
        message: content,
        session_id: sessionId.value,
        conversation_id: conversationId.value,
        history: historyForRequest,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    await readSseStream(response, async (event, payload) => {
      if (event === 'delta') {
        const chunk = typeof payload.content === 'string' ? payload.content : '';
        if (chunk) {
          ensureAssistantMessage().content += chunk;
          await scrollToBottom();
        }
        return;
      }

      if (event === 'done') {
        const data = payload as unknown as ChatResponse;
        const message = ensureAssistantMessage();
        if (!message.content) message.content = data.answer;
        message.id = data.message_id ?? undefined;
        sessionId.value = data.session_id;
        conversationId.value = data.conversation_id;
        suggestions.value = data.suggestions.length ? data.suggestions : suggestions.value;
        if (data.conversation_id) {
          emit('activeConversationChanged', data.conversation_id);
          emit('conversationUpdated', data.conversation_id);
        }
        return;
      }

      const message = typeof payload.message === 'string' ? payload.message : '流式回答失败';
      throw new Error(message);
    });
  } catch {
    if (requestController.signal.aborted) return;
    errorText.value = '客服服务暂时不可用，请确认 Python 后端已启动。';
    const message = ensureAssistantMessage();
    if (!message.content) {
      message.content = '抱歉，我暂时无法连接客服服务。请稍后再试，或联系人工客服处理。';
    } else {
      message.content += '\n\n连接已中断，请稍后重试。';
    }
  } finally {
    // 清空后可能已经开始下一次请求，旧请求不能覆盖新请求的发送状态。
    if (activeRequestController === requestController) {
      activeRequestController = null;
      isSending.value = false;
      hasReceivedChunk.value = false;
      await scrollToBottom();
    }
  }
};

const submitFeedback = async (message: ChatMessage, feedbackType: 'helpful' | 'unhelpful') => {
  if (!message.id || !conversationId.value) return;

  try {
    const response = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: conversationId.value,
        message_id: message.id,
        feedback_type: feedbackType,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    message.feedback = feedbackType;
  } catch {
    errorText.value = '评价保存失败，请稍后再试。';
  }
};

const submitConversationRating = async (rating: number) => {
  const message = latestAssistantMessage.value;
  if (!message?.id || !conversationId.value || isRatingSaving.value) return;

  isRatingSaving.value = true;
  errorText.value = '';
  try {
    const response = await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: conversationId.value,
        message_id: message.id,
        // 三星及以上表示基本认可；一至二星会进入低评分问题收集流程。
        feedback_type: rating >= 3 ? 'helpful' : 'unhelpful',
        rating,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    conversationRating.value = rating;
    message.feedback = rating >= 3 ? 'helpful' : 'unhelpful';
  } catch {
    errorText.value = '评价保存失败，请稍后再试。';
  } finally {
    isRatingSaving.value = false;
  }
};

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    void sendMessage();
  }
};
</script>

<template>
  <section class="chat-workspace">
    <div class="chat-header">
      <div class="bot-avatar" aria-hidden="true">
        <Bot :size="20" :stroke-width="2.2" />
      </div>
      <div>
        <h2>您好，我是智能客服小智</h2>
        <p>很高兴为您服务，请问有什么可以帮助您?</p>
      </div>
    </div>

    <div ref="conversationRef" class="conversation">
      <div v-if="isHistoryLoading" class="conversation-state" aria-live="polite">
        <span class="conversation-loader" aria-hidden="true"></span>
        <strong>正在加载对话内容</strong>
        <span>马上为你恢复本次咨询</span>
      </div>

      <div v-else-if="historyLoadError" class="conversation-state conversation-state-error" role="alert">
        <strong>历史消息加载失败</strong>
        <span>{{ historyLoadError }}</span>
        <button
          v-if="historyRetryConversation"
          type="button"
          @click="openConversation(historyRetryConversation)"
        >
          重新加载
        </button>
      </div>

      <div v-else-if="!messages.length" class="conversation-state conversation-welcome">
        <span class="welcome-orb" aria-hidden="true"><Bot :size="27" :stroke-width="2.1" /></span>
        <strong>你好，需要咨询什么问题？</strong>
        <span>可以直接输入问题，也可以从下方推荐中选择</span>
      </div>

      <template v-else>
        <div
          v-for="(message, index) in messages"
          :key="message.id || `${message.time}-${index}`"
          class="message-row"
          :class="message.role"
        >
          <div v-if="message.role === 'assistant'" class="bot-avatar small" aria-hidden="true">
            <Bot :size="17" :stroke-width="2.2" />
          </div>
          <article
            class="message-bubble"
            :class="message.role === 'user' ? 'user-bubble' : 'assistant-card'"
          >
            <p v-if="message.streaming && !message.content">正在读取已发布知识，请稍候...</p>
            <p v-for="(line, lineIndex) in message.content.split('\n')" v-else :key="lineIndex">
              {{ line }}
            </p>
            <time>{{ message.time }}</time>
            <div v-if="message.role === 'assistant' && message.id" class="feedback">
              <button
                type="button"
                :disabled="Boolean(message.feedback)"
                @click="submitFeedback(message, 'helpful')"
              >
                <span aria-hidden="true">♡</span>
                {{ message.feedback === 'helpful' ? '已评价' : '有帮助' }}
              </button>
              <button
                type="button"
                :disabled="Boolean(message.feedback)"
                @click="submitFeedback(message, 'unhelpful')"
              >
                <span aria-hidden="true">◇</span>
                {{ message.feedback === 'unhelpful' ? '已评价' : '没帮助' }}
              </button>
            </div>
          </article>
          <div v-if="message.role === 'user'" class="user-avatar" aria-hidden="true">
            <UserRound :size="18" />
          </div>
        </div>
      </template>

      <div v-if="isSending && !hasReceivedChunk" class="message-row assistant">
        <div class="bot-avatar small" aria-hidden="true"><Bot :size="17" /></div>
        <article class="message-bubble assistant-card">
          <p>正在为您查询，请稍候...</p>
        </article>
      </div>

      <div class="recommend-row">
        <h3>相关推荐</h3>
        <div class="suggestions">
          <button v-for="item in suggestions" :key="item" type="button" @click="sendMessage(item)">
            {{ item }}
          </button>
        </div>
      </div>
    </div>

    <section class="conversation-rating" aria-label="本次对话评价">
      <div class="conversation-rating-copy">
        <strong>本次对话评价</strong>
        <span>
          {{
            conversationRating
              ? '感谢您的评价'
              : latestAssistantMessage
                ? '这次服务体验如何？'
                : '完成一次咨询后即可评价'
          }}
        </span>
      </div>
      <div class="conversation-rating-stars">
        <button
          v-for="star in 5"
          :key="star"
          type="button"
          :class="{ active: conversationRating !== null && star <= conversationRating }"
          :disabled="!latestAssistantMessage || isRatingSaving"
          :aria-label="`${star}星评价`"
          @click="submitConversationRating(star)"
        >
          <span aria-hidden="true">★</span>
        </button>
      </div>
    </section>

    <footer class="input-area">
      <div class="input-tabs" role="tablist" aria-label="输入方式">
        <button class="active" type="button">
          <Keyboard :size="17" aria-hidden="true" />文字输入
        </button>
        <button type="button"><Mic :size="17" aria-hidden="true" />语音输入</button>
      </div>
      <div class="composer-row">
        <div class="composer">
          <textarea
            ref="textareaRef"
            v-model="inputValue"
            placeholder="请输入您的问题，支持文字或语音..."
            rows="3"
            :disabled="isHistoryLoading || isFaqAnswering"
            @keydown="handleKeydown"
          ></textarea>
          <div class="composer-tools">
            <div ref="emojiPickerRef" class="emoji-picker-wrap">
              <button
                class="emoji-trigger"
                :class="{ active: isEmojiPickerOpen }"
                type="button"
                aria-label="选择表情"
                aria-controls="emoji-picker"
                :aria-expanded="isEmojiPickerOpen"
                :disabled="isHistoryLoading || isFaqAnswering"
                @click="toggleEmojiPicker"
              >
                <Smile :size="18" />
              </button>
              <div
                v-if="isEmojiPickerOpen"
                id="emoji-picker"
                class="emoji-picker"
                role="dialog"
                aria-label="表情选择"
              >
                <div class="emoji-picker-heading">
                  <strong>常用表情</strong>
                </div>
                <div class="emoji-grid" role="list">
                  <button
                    v-for="emoji in emojis"
                    :key="emoji"
                    type="button"
                    role="listitem"
                    :aria-label="`插入表情 ${emoji}`"
                    @click="insertEmoji(emoji)"
                  >
                    {{ emoji }}
                  </button>
                </div>
              </div>
            </div>
          </div>
          <button
            class="send-button"
            type="button"
            aria-label="发送"
            :disabled="isSending || isHistoryLoading || isFaqAnswering"
            @click="sendMessage()"
          >
            <Send :size="18" :stroke-width="2.2" aria-hidden="true" />
          </button>
        </div>
        <button class="talk-button" type="button" aria-label="点击说话">
          <span class="large-mic" aria-hidden="true"><Mic :size="24" /></span>
          <small>点击说话</small>
        </button>
      </div>
      <p v-if="errorText" class="error-tip">{{ errorText }}</p>
      <p class="send-tip">按 Enter 发送，Shift + Enter 换行</p>
    </footer>

    <p class="disclaimer">智能客服小智提供服务<br />内容由AI生成，仅供参考</p>
  </section>
</template>
