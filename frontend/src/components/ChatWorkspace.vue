<script setup lang="ts">
import { nextTick, ref } from 'vue';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  time: string;
}

interface ChatResponse {
  answer: string;
  session_id: string;
  provider: string;
  suggestions: string[];
}

const messages = ref<ChatMessage[]>([
  { role: 'user', content: '我的奖励什么时候到账?', time: '10:30' },
  {
    role: 'assistant',
    content:
      '为您查询到以下信息：\n您参与的“消费返现活动”奖励将在满足活动条件后的3个工作日内发放到您的账户中。\n您的奖励预计到账时间：2024-06-01\n如有疑问，您可以查看活动规则或联系客服人工客服。',
    time: '10:30',
  },
  { role: 'user', content: '为什么我的奖励还没到账?', time: '10:31' },
  {
    role: 'assistant',
    content:
      '为您查询到以下原因：\n1. 您已满足活动消费条件\n2. 系统正在处理您的奖励发放\n3. 预计在 2024-06-01 前到账\n如长时间未到账，建议您联系客服处理。',
    time: '10:31',
  },
]);

const inputValue = ref('');
const isSending = ref(false);
const errorText = ref('');
const sessionId = ref<string | null>(null);
const suggestions = ref(['奖励未到账怎么办?', '如何查询我的权益?', '活动规则有哪些?']);
const conversationRef = ref<HTMLElement | null>(null);

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

const sendMessage = async (preset?: string) => {
  const content = (preset ?? inputValue.value).trim();
  if (!content || isSending.value) return;

  errorText.value = '';
  inputValue.value = '';
  messages.value.push({ role: 'user', content, time: currentTime() });
  isSending.value = true;
  await scrollToBottom();

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: content,
        session_id: sessionId.value,
        history: messages.value.slice(-10).map((item) => ({
          role: item.role,
          content: item.content,
        })),
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = (await response.json()) as ChatResponse;
    sessionId.value = data.session_id;
    suggestions.value = data.suggestions.length ? data.suggestions : suggestions.value;
    messages.value.push({
      role: 'assistant',
      content: data.answer,
      time: currentTime(),
    });
  } catch {
    errorText.value = '客服服务暂时不可用，请确认 Python 后端已启动。';
    messages.value.push({
      role: 'assistant',
      content: '抱歉，我暂时无法连接客服服务。请稍后再试，或联系人工客服处理。',
      time: currentTime(),
    });
  } finally {
    isSending.value = false;
    await scrollToBottom();
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
        <span>• •</span>
      </div>
      <div>
        <h2>您好，我是智能客服小智</h2>
        <p>很高兴为您服务，请问有什么可以帮助您?</p>
      </div>
    </div>

    <div ref="conversationRef" class="conversation">
      <div
        v-for="(message, index) in messages"
        :key="`${message.time}-${index}`"
        class="message-row"
        :class="message.role"
      >
        <div v-if="message.role === 'assistant'" class="bot-avatar small" aria-hidden="true">
          <span>• •</span>
        </div>
        <article
          class="message-bubble"
          :class="message.role === 'user' ? 'user-bubble' : 'assistant-card'"
        >
          <p v-for="line in message.content.split('\n')" :key="line">{{ line }}</p>
          <time>{{ message.time }}</time>
          <div v-if="message.role === 'assistant' && index === 1" class="card-actions">
            <button type="button" @click="sendMessage('查看活动规则')">查看活动规则</button>
            <button type="button" @click="sendMessage('查看我的奖励')">查看我的奖励</button>
          </div>
          <div v-if="message.role === 'assistant' && index > 1" class="feedback">
            <button type="button"><span aria-hidden="true">♡</span> 有帮助</button>
            <button type="button"><span aria-hidden="true">◇</span> 没帮助</button>
          </div>
        </article>
        <div v-if="message.role === 'user'" class="user-avatar" aria-hidden="true"></div>
      </div>

      <div v-if="isSending" class="message-row assistant">
        <div class="bot-avatar small" aria-hidden="true"><span>• •</span></div>
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

    <footer class="input-area">
      <div class="input-tabs" role="tablist" aria-label="输入方式">
        <button class="active" type="button">
          <span class="keyboard-icon" aria-hidden="true"></span>文字输入
        </button>
        <button type="button"><span class="mic-line" aria-hidden="true"></span>语音输入</button>
      </div>
      <div class="composer-row">
        <div class="composer">
          <textarea
            v-model="inputValue"
            placeholder="请输入您的问题，支持文字或语音..."
            rows="3"
            @keydown="handleKeydown"
          ></textarea>
          <div class="composer-tools">
            <button type="button" aria-label="表情">☺</button>
            <button type="button" aria-label="图片">▧</button>
            <button type="button" aria-label="文件">▤</button>
          </div>
          <button
            class="send-button"
            type="button"
            aria-label="发送"
            :disabled="isSending"
            @click="sendMessage()"
          ></button>
        </div>
        <button class="talk-button" type="button" aria-label="点击说话">
          <span class="large-mic" aria-hidden="true"></span>
          <small>点击说话</small>
        </button>
      </div>
      <p v-if="errorText" class="error-tip">{{ errorText }}</p>
      <p class="send-tip">按 Enter 发送，Shift + Enter 换行</p>
    </footer>

    <p class="disclaimer">智能客服小智提供服务<br />内容由AI生成，仅供参考</p>
  </section>
</template>
