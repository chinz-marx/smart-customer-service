<script setup lang="ts">
import { computed, ref } from 'vue';
import { Plus, RefreshCw, Sparkles, Trash2 } from '@lucide/vue';
import {
  generateKnowledgeQuestions,
  splitKnowledgeContent,
} from '../services/questionGenerationApi';

interface QuestionDraft {
  id: number;
  text: string;
}

interface ChunkDraft {
  id: number;
  content: string;
  questions: QuestionDraft[];
}

const props = defineProps<{ content: string; title?: string }>();

const questionCount = ref(3);
const chunks = defineModel<ChunkDraft[]>({ required: true });
const generating = ref(false);
const generatingChunkId = ref<number | null>(null);
const generationError = ref('');
let draftSequence = 0;

const hasContent = computed(() => Boolean(props.content.trim()));

/**
 * 根据正文生成审批前原子分片，再由Python批量调用LLM生成标准问法。
 *
 * 只有分片和所有问法都成功返回时才替换页面草稿，避免模型临时故障
 * 清空用户已经人工修改过的内容。
 */
async function generateChunks() {
  if (!hasContent.value || generating.value) return;
  generating.value = true;
  generationError.value = '';
  try {
    const serverChunks = await splitKnowledgeContent(props.content);
    const generated = await generateKnowledgeQuestions(
      props.title ?? '',
      normalizedQuestionCount(),
      serverChunks,
    );
    const questionsByChunk = new Map(
      generated.map((item) => [item.chunkNo, item.questions]),
    );
    chunks.value = serverChunks.map((chunk) =>
      createChunk(chunk.content, questionsByChunk.get(chunk.chunkNo) ?? []),
    );
  } catch (cause) {
    generationError.value = errorMessage(cause);
  } finally {
    generating.value = false;
  }
}

function createChunk(content = '', questions: string[] = []): ChunkDraft {
  return {
    id: nextDraftId(),
    content,
    questions: questions.map((text) => ({ id: nextDraftId(), text })),
  };
}

/**
 * 只重新生成当前分片的问法，并把已有问法作为排除项发送给模型。
 * 请求失败时保留当前问法，用户可以继续编辑或再次尝试。
 */
async function regenerateQuestions(chunk: ChunkDraft) {
  if (!chunk.content.trim() || generatingChunkId.value !== null) return;
  generatingChunkId.value = chunk.id;
  generationError.value = '';
  try {
    const generated = await generateKnowledgeQuestions(
      props.title ?? '',
      normalizedQuestionCount(),
      [{
        chunkNo: 0,
        content: chunk.content.trim(),
        excludedQuestions: chunk.questions.map((question) => question.text),
      }],
    );
    chunk.questions = (generated[0]?.questions ?? []).map((text) => ({
      id: nextDraftId(),
      text,
    }));
  } catch (cause) {
    generationError.value = errorMessage(cause);
  } finally {
    generatingChunkId.value = null;
  }
}

function addChunk() {
  chunks.value.push(createChunk());
}

function removeChunk(chunkId: number) {
  chunks.value = chunks.value.filter((chunk) => chunk.id !== chunkId);
}

function addQuestion(chunk: ChunkDraft) {
  chunk.questions.push({ id: nextDraftId(), text: '' });
}

function removeQuestion(chunk: ChunkDraft, questionId: number) {
  chunk.questions = chunk.questions.filter((question) => question.id !== questionId);
}

function normalizedQuestionCount(): number {
  return Math.min(8, Math.max(1, Number(questionCount.value) || 3));
}

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : '标准问法生成失败，请稍后重试';
}

function nextDraftId(): number {
  draftSequence += 1;
  return Date.now() * 100 + draftSequence;
}
</script>

<template>
  <section class="chunk-editor" aria-labelledby="chunk-editor-title">
    <div class="chunk-editor-heading">
      <div>
        <h3 id="chunk-editor-title">原子分片与标准问法</h3>
        <p>一个知识内容可生成多个原子分片，每个分片默认生成 3 个标准问法</p>
      </div>
      <div class="chunk-editor-tools">
        <label>
          <span>每个分片问法数</span>
          <input v-model.number="questionCount" type="number" min="1" max="8" />
        </label>
        <button class="chunk-generate" type="button" :disabled="!hasContent || generating || generatingChunkId !== null" @click="generateChunks">
          <RefreshCw v-if="generating" class="spin" :size="15" />
          <Sparkles v-else :size="15" />
          {{ generating ? '生成中' : '生成分片' }}
        </button>
      </div>
    </div>

    <div v-if="generationError" class="chunk-error">{{ generationError }}</div>

    <div v-if="!chunks.length" class="chunk-empty">
      填写知识内容后点击“生成分片”，即可预览分片与问法的对应关系
    </div>

    <article v-for="(chunk, chunkIndex) in chunks" :key="chunk.id" class="chunk-draft">
      <header>
        <div><strong>原子分片 {{ String(chunkIndex + 1).padStart(2, '0') }}</strong><span>已生成 {{ chunk.questions.length }} 个问法</span></div>
        <div class="chunk-actions">
          <button type="button" title="重新生成问法" :disabled="generatingChunkId !== null || !chunk.content.trim()" @click="regenerateQuestions(chunk)"><RefreshCw :class="{ spin: generatingChunkId === chunk.id }" :size="14" />{{ generatingChunkId === chunk.id ? '生成中' : '重新生成' }}</button>
          <button type="button" title="删除原子分片" @click="removeChunk(chunk.id)"><Trash2 :size="14" />删除</button>
        </div>
      </header>
      <textarea v-model="chunk.content" rows="3" aria-label="原子分片内容" />
      <div class="question-heading">标准问法（{{ chunk.questions.length }}）</div>
      <div class="question-list">
        <div v-for="question in chunk.questions" :key="question.id" class="question-row">
          <input v-model="question.text" placeholder="输入与此分片对应的问法" />
          <button type="button" title="删除问法" @click="removeQuestion(chunk, question.id)"><Trash2 :size="14" /></button>
        </div>
      </div>
      <button class="question-add" type="button" @click="addQuestion(chunk)"><Plus :size="14" />添加问法</button>
    </article>

    <button class="chunk-add" type="button" @click="addChunk"><Plus :size="15" />新增原子分片</button>
  </section>
</template>

<style scoped>
.chunk-editor { display: grid; gap: 10px; padding-top: 2px; }
.chunk-editor-heading { display: flex; align-items: end; justify-content: space-between; gap: 14px; }
.chunk-editor-heading h3 { margin: 0; color: #29343e; font-size: 14px; }
.chunk-editor-heading p { margin: 5px 0 0; color: #77828d; font-size: 12px; font-weight: 400; }
.chunk-editor-tools { display: flex; align-items: end; gap: 8px; flex: none; }
.chunk-editor-tools label { display: flex; align-items: center; gap: 7px; color: #596570; white-space: nowrap; }
.chunk-editor-tools input { width: 68px; height: 34px; padding: 0 6px; text-align: center; }
.chunk-generate, .chunk-actions button, .question-add, .chunk-add { min-height: 32px; border: 1px solid #79a8df; border-radius: 5px; display: inline-flex; align-items: center; justify-content: center; gap: 5px; color: #1664c0; background: #fff; }
.chunk-generate { padding: 0 12px; font-weight: 650; }
.chunk-generate:disabled, .chunk-actions button:disabled { cursor: not-allowed; opacity: 0.55; }
.chunk-error { padding: 9px 11px; border: 1px solid #e3b2b2; border-radius: 5px; color: #9f3434; background: #fff8f8; font-size: 12px; }
.chunk-empty { min-height: 84px; padding: 20px; border: 1px dashed #cfd5db; border-radius: 5px; display: grid; place-items: center; color: #7a8590; background: #fafbfc; font-size: 12px; text-align: center; }
.chunk-draft { padding: 10px; border: 1px solid #d8dde3; border-radius: 5px; background: #fff; }
.chunk-draft > header { min-height: 27px; display: flex; align-items: start; justify-content: space-between; gap: 12px; }
.chunk-draft > header strong { color: #34404b; font-size: 13px; }
.chunk-draft > header span { margin-left: 14px; color: #7c8791; font-size: 12px; }
.chunk-actions { display: flex; flex: none; gap: 9px; }
.chunk-actions button { min-height: 26px; padding: 0; border: 0; color: #53606c; font-size: 12px; white-space: nowrap; }
.chunk-actions button:last-child { color: #8e4b4b; }
.chunk-draft textarea { min-height: 70px; margin-top: 7px; font-size: 12px; }
.question-heading { margin: 8px 0 5px; color: #46515c; font-size: 12px; font-weight: 650; }
.question-list { display: grid; gap: 5px; }
.question-row { display: grid; grid-template-columns: minmax(0, 1fr) 30px; gap: 5px; }
.question-row input { height: 32px; padding: 0 9px; font-size: 12px; }
.question-row button { width: 30px; border: 0; display: grid; place-items: center; color: #68737d; background: transparent; }
.question-add { min-height: 28px; margin-top: 7px; padding: 0 9px; font-size: 12px; }
.chunk-add { width: 100%; min-height: 34px; font-size: 12px; }
@media (max-width: 720px) {
  .chunk-editor-heading { align-items: stretch; flex-direction: column; }
  .chunk-editor-tools { justify-content: space-between; }
  .chunk-draft > header { flex-direction: column; }
}
</style>
