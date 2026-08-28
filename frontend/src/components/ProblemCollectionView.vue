<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import {
  Archive,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Filter,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  Search,
  Send,
  Sparkles,
  Trash2,
  X,
} from '@lucide/vue';
import { generateLearningAnswer } from '../services/learningAnswerApi';
import { generateLearningPackage } from '../services/learningPackageApi';
import { problemApi, type ProblemDetail, type ProblemListItem } from '../services/problemApi';
import { knowledgeApi, type Category } from '../services/knowledgeApi';

interface PackageDraft {
  title: string;
  categoryId: string;
  tags: string;
  content: string;
  standardQuestions: string[];
  testCases: Array<{
    question: string;
    caseCategory: string;
    difficulty: number;
    sourceType: number;
    expectedMatch: boolean;
  }>;
  effectiveAt: string;
  expiredAt: string;
  provider: string;
  model: string;
}

const operatorId = defineModel<string>('operatorId', { required: true });
const keyword = ref('');
const sourceType = ref('');
const status = ref('1');
const rows = ref<ProblemListItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = 50;
const loading = ref(false);
const detailLoading = ref(false);
const selected = ref<ProblemDetail | null>(null);
const answerDraft = ref('');
const reviewComment = ref('');
const rejectionReason = ref('');
const actionLoading = ref('');
const submittingReviewId = ref<number | null>(null);
const confirmingReviewId = ref<number | null>(null);
const toast = ref('');
const error = ref('');
const categories = ref<Category[]>([]);
const caseCount = ref(8);
const packageDraft = ref<PackageDraft | null>(null);

const tabs = [
  { value: '0', label: '收集中' },
  { value: '1', label: '待审核' },
  { value: '2', label: '已通过' },
  { value: '3', label: '已驳回' },
  { value: '4', label: '已转知识' },
  { value: '5', label: '已忽略' },
  { value: '', label: '全部问题' },
];

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / size)));
const pendingCount = computed(() => rows.value.filter((item) => item.status === 1).length);
const highPriorityCount = computed(() => rows.value.filter((item) => item.priority === 3).length);
const highFrequencyCount = computed(() => rows.value.filter((item) => item.occurrenceCount >= 10).length);
const totalFrequency = computed(() => rows.value.reduce((sum, item) => sum + item.occurrenceCount, 0));
const canReview = computed(() => selected.value?.problem.status === 1);

onMounted(() => { void Promise.all([loadRows(), loadCategories()]); });
watch([status, sourceType], () => { page.value = 1; void loadRows(); });

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const query = new URLSearchParams({ page: String(page.value), size: String(size) });
    if (keyword.value.trim()) query.set('keyword', keyword.value.trim());
    if (status.value) query.set('status', status.value);
    if (sourceType.value) query.set('sourceType', sourceType.value);
    const result = await problemApi.list(query);
    rows.value = result.records;
    total.value = result.total;
  } catch (reason) {
    showError(reason);
  } finally {
    loading.value = false;
  }
}

async function loadCategories() {
  try {
    categories.value = await knowledgeApi.categories();
  } catch (reason) {
    showError(reason);
  }
}

async function openDetail(item: ProblemListItem) {
  detailLoading.value = true;
  error.value = '';
  try {
    selected.value = await problemApi.detail(item.id);
    resetEditor();
  } catch (reason) {
    showError(reason);
  } finally {
    detailLoading.value = false;
  }
}

function beginSubmitForReview(item: ProblemListItem) {
  if (item.status !== 0 || !requireOperator()) return;
  confirmingReviewId.value = item.id;
  error.value = '';
}

function cancelSubmitForReview() {
  confirmingReviewId.value = null;
}

async function submitForReview(item: ProblemListItem) {
  if (item.status !== 0 || confirmingReviewId.value !== item.id || !requireOperator()) return;
  submittingReviewId.value = item.id;
  error.value = '';
  try {
    await problemApi.submitForReview(item.id, operatorId.value.trim());
    confirmingReviewId.value = null;
    notify('问题已提交审核');
    await loadRows();
  } catch (reason) {
    showError(reason);
  } finally {
    submittingReviewId.value = null;
  }
}

async function generateSuggestion() {
  if (!selected.value || !requireOperator()) return;
  actionLoading.value = 'generate';
  try {
    const generated = await generateLearningAnswer(selected.value);
    selected.value = await problemApi.saveAnswer(
      selected.value.problem.id,
      generated,
      operatorId.value.trim(),
    );
    answerDraft.value = selected.value.problem.standardAnswer || '';
    notify('LLM标准回答草稿已生成并保存，请人工检查');
    await loadRows();
  } catch (reason) {
    showError(reason);
  } finally {
    actionLoading.value = '';
  }
}

async function saveDraft() {
  if (!selected.value || !requireOperator()) return;
  if (!answerDraft.value.trim()) return showError(new Error('标准回答不能为空'));
  actionLoading.value = 'save';
  try {
    await persistDraft();
    resetEditor(false);
    notify('标准回答草稿已保存');
    await loadRows();
  } catch (reason) {
    showError(reason);
  } finally {
    actionLoading.value = '';
  }
}

async function approveProblem() {
  if (!selected.value || !requireOperator()) return;
  if (!answerDraft.value.trim()) return showError(new Error('请先生成或填写标准回答'));
  actionLoading.value = 'approve';
  try {
    if (answerDraft.value.trim() !== (selected.value.problem.standardAnswer || '').trim()) {
      // 保存失败会直接进入本函数的catch，绝不能继续发送“审核通过”。
      await persistDraft();
    }
    selected.value = await problemApi.approve(
      selected.value.problem.id, reviewComment.value.trim(), operatorId.value.trim(),
    );
    resetEditor(false);
    notify('问题审核已通过');
    await loadRows();
  } catch (reason) {
    showError(reason);
  } finally {
    actionLoading.value = '';
  }
}

async function persistDraft() {
  if (!selected.value) return;
  selected.value = await problemApi.saveAnswer(
    selected.value.problem.id,
    {
      answer: answerDraft.value.trim(),
      provider: selected.value.problem.answerProvider || 'manual',
      model: selected.value.problem.answerModel || 'manual-editor',
    },
    operatorId.value.trim(),
  );
}

async function rejectProblem() {
  if (!selected.value || !requireOperator()) return;
  if (!rejectionReason.value.trim()) return showError(new Error('请填写驳回原因'));
  actionLoading.value = 'reject';
  try {
    selected.value = await problemApi.reject(
      selected.value.problem.id,
      rejectionReason.value.trim(),
      reviewComment.value.trim(),
      operatorId.value.trim(),
    );
    resetEditor(false);
    notify('问题已驳回');
    await loadRows();
  } catch (reason) {
    showError(reason);
  } finally {
    actionLoading.value = '';
  }
}

async function ignoreProblem() {
  if (!selected.value || !requireOperator()) return;
  actionLoading.value = 'ignore';
  try {
    selected.value = await problemApi.ignore(
      selected.value.problem.id,
      reviewComment.value.trim() || '人工确认当前问题无需进入知识学习',
      operatorId.value.trim(),
    );
    resetEditor(false);
    notify('问题已忽略');
    await loadRows();
  } catch (reason) {
    showError(reason);
  } finally {
    actionLoading.value = '';
  }
}

async function generatePackage() {
  if (!selected.value || selected.value.problem.status !== 2 || !requireOperator()) return;
  actionLoading.value = 'package';
  try {
    const generated = await generateLearningPackage(selected.value, caseCount.value);
    packageDraft.value = {
      title: generated.title,
      categoryId: categories.value[0] ? String(categories.value[0].id) : '',
      tags: generated.tags.join(','),
      content: generated.content,
      standardQuestions: [...generated.standard_questions],
      testCases: generated.test_cases.map((item) => ({
        question: item.question,
        caseCategory: item.case_category,
        difficulty: ({ easy: 1, medium: 2, hard: 3 } as const)[item.difficulty],
        sourceType: item.source_type === 'real_user' ? 1 : 2,
        expectedMatch: item.expected_match,
      })),
      effectiveAt: toLocalDateTime(new Date()),
      expiredAt: '',
      provider: generated.provider,
      model: generated.model,
    };
    notify('知识草稿和回归测试用例已生成，请检查后提交审批');
  } catch (reason) {
    showError(reason);
  } finally {
    actionLoading.value = '';
  }
}

async function submitPackage() {
  if (!selected.value || !packageDraft.value || !requireOperator()) return;
  const draft = packageDraft.value;
  if (!draft.categoryId) return showError(new Error('请选择知识分类'));
  if (!draft.title.trim()) return showError(new Error('知识标题不能为空'));
  if (draft.standardQuestions.some((item) => !item.trim())) {
    return showError(new Error('标准问法不能为空'));
  }
  if (draft.testCases.length < 8 || draft.testCases.some((item) => !item.question.trim())) {
    return showError(new Error('至少保留8条非空多元测试用例'));
  }
  actionLoading.value = 'submit-package';
  try {
    const result = await problemApi.convertToKnowledge(
      selected.value.problem.id,
      {
        categoryId: Number(draft.categoryId),
        title: draft.title.trim(),
        tags: draft.tags.split(',').map((item) => item.trim()).filter(Boolean),
        effectiveAt: new Date(draft.effectiveAt).toISOString(),
        expiredAt: draft.expiredAt ? new Date(draft.expiredAt).toISOString() : undefined,
        standardQuestions: draft.standardQuestions.map((item) => item.trim()),
        testCases: draft.testCases.map((item) => ({ ...item, question: item.question.trim() })),
        provider: draft.provider,
        model: draft.model,
      },
      operatorId.value.trim(),
    );
    selected.value = await problemApi.detail(selected.value.problem.id);
    packageDraft.value = null;
    notify(`已提交知识审批，并保存 ${result.testCaseCount} 条待审批测试用例`);
    await loadRows();
  } catch (reason) {
    showError(reason);
  } finally {
    actionLoading.value = '';
  }
}

function addTestQuestion() {
  if (!packageDraft.value || packageDraft.value.testCases.length >= 15) return;
  packageDraft.value.testCases.push({
    question: '', caseCategory: 'conversational', difficulty: 2,
    sourceType: 2, expectedMatch: true,
  });
}

function removeTestQuestion(index: number) {
  if (!packageDraft.value || packageDraft.value.testCases.length <= 8) return;
  packageDraft.value.testCases.splice(index, 1);
}

function resetEditor(clearDecision = true) {
  answerDraft.value = selected.value?.problem.standardAnswer || '';
  packageDraft.value = null;
  if (clearDecision) {
    reviewComment.value = '';
    rejectionReason.value = '';
  }
}

function requireOperator(): boolean {
  if (operatorId.value.trim()) return true;
  showError(new Error('请填写操作人 ID'));
  return false;
}

function closeDetail() {
  selected.value = null;
  answerDraft.value = '';
  packageDraft.value = null;
}

function notify(message: string) {
  toast.value = message;
  error.value = '';
  window.setTimeout(() => { if (toast.value === message) toast.value = ''; }, 3000);
}

function showError(reason: unknown) {
  error.value = reason instanceof Error ? reason.message : '操作失败，请稍后重试';
  toast.value = '';
}

function sourceName(value?: number) {
  return ({ 1: '没帮助', 2: '差评', 3: '申请人工', 4: '投诉', 5: 'Tool失败', 6: 'RAG无命中' } as Record<number, string>)[value || 0] || '-';
}

function statusLabel(value: number) {
  return ['收集中', '待审核', '已通过', '已驳回', '已转知识', '已忽略'][value] || '未知';
}

function statusClass(value: number) {
  return ['collecting', 'pending', 'approved', 'rejected', 'converted', 'ignored'][value] || 'collecting';
}

function confidenceLabel(value?: number) {
  return value == null ? '-' : `${Math.round(value * 100)}%`;
}

function formatTime(value?: string) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-';
}

function toLocalDateTime(value: Date) {
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 16);
}
</script>

<template>
  <main class="kb-main collection-view">
    <header class="kb-header">
      <div><h1>问题收集</h1><p>聚合没帮助、差评、申请人工、投诉、Tool失败和RAG无命中问题，达到门槛后进入人工审核</p></div>
      <label class="operator-field">操作人 ID<input v-model="operatorId" maxlength="64" /></label>
    </header>

    <div v-if="toast" class="kb-notice success"><Check :size="17" />{{ toast }}</div>
    <div v-if="error" class="kb-notice error"><CircleAlert :size="17" />{{ error }}</div>

    <section class="ops-summary" aria-label="问题概览">
      <div><span>当前页待审核</span><strong>{{ pendingCount }}</strong></div>
      <div><span>高优先级</span><strong>{{ highPriorityCount }}</strong></div>
      <div><span>高频问题</span><strong>{{ highFrequencyCount }}</strong></div>
      <div><span>当前页累计发生</span><strong>{{ totalFrequency }}</strong></div>
    </section>

    <section class="kb-toolbar" aria-label="问题筛选">
      <form class="kb-search" @submit.prevent="page = 1; loadRows()"><Search :size="17" /><input v-model="keyword" placeholder="搜索问题摘要、原话或编号" /></form>
      <div class="filter-select"><Filter :size="16" /><select v-model="sourceType" aria-label="问题来源"><option value="">全部来源</option><option value="1">没帮助</option><option value="2">差评</option><option value="3">申请人工</option><option value="4">投诉</option><option value="5">Tool失败</option><option value="6">RAG无命中</option></select></div>
      <button class="icon-command" type="button" title="刷新" :disabled="loading" @click="loadRows"><RefreshCw :class="{ spin: loading }" :size="18" /></button>
    </section>

    <div class="kb-tabs" role="tablist">
      <button v-for="tab in tabs" :key="tab.value" :class="{ active: status === tab.value }" type="button" @click="status = tab.value">{{ tab.label }}</button>
    </div>

    <section class="kb-table-section problem-table-section">
      <div class="table-summary"><strong>{{ total }}</strong> 条问题<span>投诉、高频及多用户受影响问题优先处理</span></div>
      <div class="kb-table-scroll">
        <table>
          <thead><tr><th>问题摘要</th><th>主要来源</th><th>识别意图</th><th>置信度</th><th>频次</th><th>影响用户</th><th>最近发生</th><th>状态</th><th class="actions">操作</th></tr></thead>
          <tbody>
            <tr v-if="loading"><td colspan="9" class="empty"><LoaderCircle class="spin" :size="17" />正在加载问题</td></tr>
            <tr v-else-if="!rows.length"><td colspan="9" class="empty">没有符合条件的问题</td></tr>
            <tr v-for="item in rows" v-else :key="item.id">
              <td class="problem-summary"><button type="button" @click="openDetail(item)">{{ item.problemSummary }}</button><small>{{ item.problemCode }} · {{ item.representativeQuestion }}</small></td>
              <td><span class="source-badge">{{ sourceName(item.sourceType) }}</span></td>
              <td>{{ item.intentCode || '-' }}</td>
              <td><span :class="['confidence', { low: (item.confidence || 0) < 0.65 }]">{{ confidenceLabel(item.confidence) }}</span></td>
              <td><strong>{{ item.occurrenceCount }}</strong></td>
              <td>{{ item.affectedUserCount }}</td>
              <td>{{ formatTime(item.lastSeenAt) }}</td>
              <td><span class="status" :class="statusClass(item.status)">{{ statusLabel(item.status) }}</span></td>
              <td class="row-actions">
                <div class="row-action-buttons">
                  <button title="查看并处理" type="button" @click="openDetail(item)"><ChevronRight :size="16" /></button>
                  <button v-if="item.status === 0 && confirmingReviewId !== item.id" class="submit-review-command" type="button" :disabled="submittingReviewId !== null" @click="beginSubmitForReview(item)"><Send :size="14" />提交审核</button>
                  <template v-else-if="item.status === 0">
                    <span class="inline-confirm-label">确认提交？</span>
                    <button class="inline-cancel-command" type="button" :disabled="submittingReviewId === item.id" @click="cancelSubmitForReview">取消</button>
                    <button class="submit-review-command" type="button" :disabled="submittingReviewId === item.id" @click="submitForReview(item)"><LoaderCircle v-if="submittingReviewId === item.id" class="spin" :size="14" /><Send v-else :size="14" />确认提交</button>
                  </template>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="kb-pagination"><span>第 {{ page }} / {{ pageCount }} 页</span><button title="上一页" :disabled="page <= 1" @click="page--; loadRows()"><ChevronLeft :size="16" /></button><button title="下一页" :disabled="page >= pageCount" @click="page++; loadRows()"><ChevronRight :size="16" /></button></div>
    </section>

    <div v-if="selected" class="kb-overlay" @click.self="closeDetail">
      <aside class="problem-drawer" aria-modal="true" role="dialog">
        <header><div><h2>问题审核</h2><p>{{ selected.problem.problemCode }} · 版本 {{ selected.problem.reviewVersion }}</p></div><button title="关闭" @click="closeDetail"><X :size="20" /></button></header>
        <div v-if="detailLoading" class="drawer-loading"><LoaderCircle class="spin" :size="20" />加载详情</div>
        <div v-else class="problem-detail">
          <div class="detail-heading"><CircleAlert :size="20" /><div><h3>{{ selected.problem.problemSummary }}</h3><p>{{ sourceName(selected.problem.sourceType) }} · 发生 {{ selected.problem.occurrenceCount }} 次 · 影响 {{ selected.problem.affectedUserCount }} 位用户</p></div></div>
          <div v-if="selected.problem.rejectionReason" class="rejection-panel"><strong>驳回原因</strong><p>{{ selected.problem.rejectionReason }}</p></div>
          <label>代表问法<textarea :value="selected.problem.representativeQuestion" rows="3" readonly /></label>
          <div class="detail-grid"><label>识别意图<input :value="selected.problem.intentCode || '-'" readonly /></label><label>平均置信度<input :value="confidenceLabel(selected.problem.confidence)" readonly /></label></div>

          <section class="sample-section"><h3>真实问题样本</h3><article v-for="sample in selected.samples" :key="sample.id"><div><span class="source-badge">{{ sourceName(sample.sourceType) }}</span><time>{{ formatTime(sample.occurredAt) }}</time></div><p>{{ sample.rootQuestion }}</p><small v-if="sample.originalAnswer">原回答：{{ sample.originalAnswer }}</small></article></section>

          <section class="answer-workbench">
            <header>
              <div><h3>标准回答草稿</h3><p>生成或编辑后先保存，再进行审核决策</p></div>
              <div v-if="canReview" class="answer-workbench-actions">
                <button class="secondary-command" type="button" :disabled="!!actionLoading" @click="generateSuggestion"><LoaderCircle v-if="actionLoading === 'generate'" class="spin" :size="16" /><Sparkles v-else :size="16" />LLM生成回答</button>
                <button class="secondary-command" type="button" :disabled="!!actionLoading" @click="saveDraft"><LoaderCircle v-if="actionLoading === 'save'" class="spin" :size="16" /><Save v-else :size="16" />保存草稿</button>
              </div>
            </header>
            <textarea v-model="answerDraft" aria-label="标准回答草稿" rows="8" :readonly="!canReview" placeholder="由LLM生成后人工检查和编辑，不会自动发布" />
            <div v-if="selected.problem.answerModel" class="answer-meta">生成模型：{{ selected.problem.answerModel }} · 生成人：{{ selected.problem.answerGeneratedBy }} · {{ formatTime(selected.problem.answerGeneratedAt) }}</div>
          </section>

          <section v-if="canReview" class="review-notes-section">
            <header><div><h3>审核意见</h3><p>备注用于记录判断依据，驳回时必须填写原因</p></div></header>
            <div class="review-notes-grid">
              <label>审核备注<textarea v-model="reviewComment" rows="3" placeholder="可选，记录判断依据" /></label>
              <label>驳回原因<textarea v-model="rejectionReason" rows="3" placeholder="驳回时必填" /></label>
            </div>
          </section>

          <section v-if="selected.problem.status === 2" class="learning-package-section">
            <header><div><h3>知识草稿与测试集</h3><p>正文使用已审核答案，测试集必须覆盖多元表达和困难负样本</p></div><label>测试用例数<select v-model.number="caseCount"><option :value="8">8条</option><option :value="10">10条</option><option :value="12">12条</option><option :value="15">15条</option></select></label></header>
            <button v-if="!packageDraft" class="secondary-command" type="button" :disabled="!!actionLoading" @click="generatePackage"><LoaderCircle v-if="actionLoading === 'package'" class="spin" :size="16" /><Sparkles v-else :size="16" />生成知识草稿与测试集</button>
            <div v-else class="package-editor">
              <section class="package-form-section">
                <header><div><h4>知识信息</h4><p>确认标题、分类和正文内容</p></div></header>
                <label>知识标题<input v-model="packageDraft.title" maxlength="256" /></label>
                <div class="package-field-grid"><label>知识分类<select v-model="packageDraft.categoryId"><option value="">请选择</option><option v-for="category in categories" :key="category.id" :value="String(category.id)">{{ category.categoryName }}</option></select></label><label>标签<input v-model="packageDraft.tags" placeholder="多个标签用逗号分隔" /></label></div>
                <label>知识正文<textarea v-model="packageDraft.content" rows="6" readonly /><small>正文来自已审核标准回答；需要修改请重新进行问题审核。</small></label>
              </section>

              <section class="package-form-section">
                <header><div><h4>发布设置</h4><p>设置知识生效和失效时间</p></div></header>
                <div class="package-field-grid"><label>生效时间<input v-model="packageDraft.effectiveAt" type="datetime-local" /></label><label>失效时间<input v-model="packageDraft.expiredAt" type="datetime-local" /></label></div>
              </section>

              <section class="package-form-section standard-question-section">
                <header><div><h4>向量标准问法</h4><p>用于提升相似问题的召回准确率</p></div><span class="package-count">{{ packageDraft.standardQuestions.length }} 条</span></header>
                <div class="standard-question-list">
                  <label v-for="(_, index) in packageDraft.standardQuestions" :key="`standard-${index}`" class="standard-question-row"><span class="question-index">{{ index + 1 }}</span><input v-model="packageDraft.standardQuestions[index]" :aria-label="`标准问法 ${index + 1}`" /></label>
                </div>
              </section>

              <section class="package-form-section test-case-section">
                <header>
                  <div><h4>多元回归测试用例</h4><p>逐条检查问法、表达类型和预期结果</p></div>
                  <div class="test-case-header-actions"><span class="package-count">{{ packageDraft.testCases.length }} 条</span><button class="icon-command" type="button" title="增加测试用例" :disabled="packageDraft.testCases.length >= 15" @click="addTestQuestion"><Plus :size="16" /></button></div>
                </header>
                <div class="test-case-list">
                  <article v-for="(item, index) in packageDraft.testCases" :key="`test-${index}`" class="test-case-card">
                    <header>
                      <strong>用例 {{ index + 1 }}</strong>
                      <div class="test-case-badges"><span class="source-badge">{{ item.sourceType === 1 ? '真实用户' : 'LLM生成' }}</span><span class="source-badge" :class="{ negative: !item.expectedMatch }">{{ item.expectedMatch ? '应命中' : '不应命中' }}</span><button type="button" title="删除测试用例" :disabled="packageDraft.testCases.length <= 8" @click="removeTestQuestion(index)"><Trash2 :size="15" /></button></div>
                    </header>
                    <label class="test-question-field">测试问法<input v-model="item.question" /></label>
                    <div class="test-case-settings"><label>表达类型<select v-model="item.caseCategory"><option value="conversational">口语</option><option value="omitted">省略</option><option value="typo">错别字</option><option value="inverted">倒装/追问</option><option value="boundary">边界</option><option value="hard_negative">困难负样本</option></select></label><label>难度<select v-model.number="item.difficulty"><option :value="1">简单</option><option :value="2">中等</option><option :value="3">困难</option></select></label></div>
                  </article>
                </div>
              </section>
              <div class="package-actions"><button class="secondary-command" type="button" :disabled="!!actionLoading" @click="generatePackage"><RefreshCw :size="16" />重新生成</button><button class="primary-command" type="button" :disabled="!!actionLoading" @click="submitPackage"><LoaderCircle v-if="actionLoading === 'submit-package'" class="spin" :size="16" /><Check v-else :size="16" />提交知识审批</button></div>
            </div>
          </section>

          <div v-if="selected.problem.status === 4" class="conversion-result"><Check :size="18" /><div><strong>已进入知识审批</strong><p>知识ID {{ selected.problem.convertedKnowledgeId }} · 版本ID {{ selected.problem.convertedVersionId }} · 审批ID {{ selected.problem.convertedApprovalId }}</p></div></div>

          <section v-if="selected.reviews.length" class="review-history"><h3>审核记录</h3><article v-for="review in selected.reviews" :key="review.id"><div><strong>{{ review.operatorId }}</strong><time>{{ formatTime(review.createdAt) }}</time></div><p>{{ review.comment || '已记录操作' }}</p></article></section>

          <div v-if="selected.problem.status === 0 || canReview || (selected.problem.status === 2 && !packageDraft)" class="detail-actions">
            <div class="detail-action-copy">
              <strong>{{ canReview ? '审核决策' : selected.problem.status === 2 ? '下一步' : '问题处置' }}</strong>
              <span>{{ canReview ? '确认标准回答无误后再通过' : selected.problem.status === 2 ? '生成知识草稿与回归测试集' : '确认无需处理后可忽略' }}</span>
            </div>
            <div class="detail-action-buttons">
              <button v-if="selected.problem.status === 0 || canReview" class="secondary-command ignore-command" type="button" :disabled="!!actionLoading" @click="ignoreProblem"><Archive :size="16" />忽略问题</button>
              <div v-if="canReview" class="review-decision-buttons">
                <button class="reject-command" type="button" :disabled="!!actionLoading" @click="rejectProblem"><X :size="16" />驳回</button>
                <button class="approve-command" type="button" :disabled="!!actionLoading" @click="approveProblem"><Check :size="16" />审核通过</button>
              </div>
              <button v-if="selected.problem.status === 2 && !packageDraft" class="approve-command" type="button" :disabled="!!actionLoading" @click="generatePackage"><Sparkles :size="16" />生成知识草稿</button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </main>
</template>
