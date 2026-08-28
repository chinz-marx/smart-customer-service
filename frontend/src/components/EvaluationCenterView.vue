<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  FileJson,
  LoaderCircle,
  RefreshCw,
  TrendingUp,
} from '@lucide/vue';
import {
  listEvaluationCases,
  listEvaluationRunResults,
  listEvaluationRuns,
  type EvaluationCaseItem,
  type EvaluationRunCaseResultItem,
  type EvaluationRunItem,
} from '../services/evaluationCaseApi';
import {
  benchmarkReportUrl,
  getBenchmarkRun,
  listBenchmarkDatasets,
  listBenchmarkRuns,
  startBenchmarkRun,
  type BenchmarkDataset,
  type BenchmarkRun,
} from '../services/offlineBenchmarkApi';

const operatorId = defineModel<string>('operatorId', { required: true });
const toast = ref('');
const caseStatus = ref('');
const generatedCases = ref<EvaluationCaseItem[]>([]);
const generatedCaseTotal = ref(0);
const caseGroupPage = ref(1);
const caseGroupsPerPage = 5;
const casesLoading = ref(false);
const runsLoading = ref(false);
const error = ref('');
const expandedCaseGroupKeys = ref<string[]>([]);
const expandedRunId = ref<number | null>(null);
const runResults = ref<Record<number, EvaluationRunCaseResultItem[]>>({});
const runResultsLoadingId = ref<number | null>(null);

const releaseRuns = ref<EvaluationRunItem[]>([]);
const benchmarkDatasets = ref<BenchmarkDataset[]>([]);
const benchmarkRuns = ref<BenchmarkRun[]>([]);
const selectedDatasetId = ref('');
const benchmarkLoading = ref(false);
const benchmarkStarting = ref(false);
const activeBenchmarkRun = ref<BenchmarkRun | null>(null);
let benchmarkTimer: number | undefined;

onMounted(async () => {
  await Promise.all([loadGeneratedCases(), loadEvaluationRuns(), loadBenchmarks()]);
});
onUnmounted(() => stopBenchmarkPolling());

const latestRun = computed(() => releaseRuns.value[0]);
const selectedRun = computed(() => releaseRuns.value.find((item) => item.id === expandedRunId.value) || latestRun.value);
const selectedRunResults = computed(() => selectedRun.value ? runResults.value[selectedRun.value.id] || [] : []);
const failedRunCases = computed(() => selectedRunResults.value.filter((item) => !item.passedThreshold || item.errorMessage));
const generatedCaseGroups = computed(() => {
  const groups = new Map<string, {
    key: string;
    knowledgeCode: string;
    knowledgeTitle: string;
    versionId: number;
    versionNo: number;
    problemCode: string;
    cases: EvaluationCaseItem[];
    positiveCases: number;
    hardNegativeCases: number;
    status: number;
  }>();
  generatedCases.value.forEach((item) => {
    const key = `${item.knowledgeCode}:${item.versionId}`;
    const group = groups.get(key) || {
      key,
      knowledgeCode: item.knowledgeCode,
      knowledgeTitle: item.knowledgeTitle,
      versionId: item.versionId,
      versionNo: item.versionNo,
      problemCode: item.problemCode,
      cases: [],
      positiveCases: 0,
      hardNegativeCases: 0,
      status: item.status,
    };
    group.cases.push(item);
    if (item.expectedMatch) group.positiveCases += 1;
    else group.hardNegativeCases += 1;
    group.status = Math.min(group.status, item.status);
    groups.set(key, group);
  });
  return Array.from(groups.values());
});
const caseGroupTotalPages = computed(() => Math.max(1, Math.ceil(generatedCaseGroups.value.length / caseGroupsPerPage)));
const pagedCaseGroups = computed(() => generatedCaseGroups.value.slice(
  (caseGroupPage.value - 1) * caseGroupsPerPage,
  caseGroupPage.value * caseGroupsPerPage,
));
const allRunResultsByCaseId = computed(() => {
  const index = new Map<number, EvaluationRunCaseResultItem>();
  Object.values(runResults.value).flat().forEach((item) => index.set(item.caseId, item));
  return index;
});
const selectedDataset = computed(() => benchmarkDatasets.value.find((item) => item.id === selectedDatasetId.value));
const latestBenchmarkRun = computed(() => activeBenchmarkRun.value || benchmarkRuns.value[0]);

const releaseGateRows = computed(() => {
  const run = selectedRun.value;
  return [
    { label: 'R@1', detail: '第一名命中目标知识', value: percent(run?.recallAt1), requirement: '要求 ≥ 80%', passed: run?.recallAt1 != null && run.recallAt1 >= 0.8 },
    { label: 'R@3', detail: '前三名包含目标知识', value: percent(run?.recallAt3), requirement: '要求 = 100%', passed: run?.recallAt3 != null && run.recallAt3 >= 1 },
    { label: '阈值召回', detail: `正样本距离 ≤ ${run?.distanceThreshold ?? 0.38}`, value: percent(run?.thresholdRecall), requirement: '要求 ≥ 80%', passed: run?.thresholdRecall != null && run.thresholdRecall >= 0.8 },
    { label: '负样本误命中', detail: '困难负样本不应命中', value: percent(run?.hardNegativeFalsePositiveRate), requirement: '要求 = 0%', passed: run?.hardNegativeFalsePositiveRate != null && run.hardNegativeFalsePositiveRate <= 0 },
    { label: '执行错误', detail: '单条评测执行异常', value: run?.errorCount?.toString() ?? '-', requirement: '要求 = 0', passed: run?.errorCount === 0 },
  ];
});
const benchmarkMetricRows = computed(() => {
  const run = latestBenchmarkRun.value;
  if (!run || !Object.keys(run.metrics).length) return [];
  const metric = (name: string) => run.metrics[name] as number | undefined;
  if (run.evaluation_type === 'retrieval') return [
    { label: '样本数', value: String(metric('total_cases') ?? run.case_count) },
    { label: '知识 Recall@1', value: percent(metric('knowledge_recall_at_1')) },
    { label: '知识 Recall@3', value: percent(metric('knowledge_recall_at_3')) },
    { label: '分片 Recall@3', value: percent(metric('chunk_recall_at_3')) },
    { label: '执行错误', value: String(metric('error_count') ?? '-') },
  ];
  return [
    { label: '样本数', value: String(metric('total_cases') ?? run.case_count) },
    { label: '意图准确率', value: percent(metric('intent_accuracy')) },
    { label: '槽位准确率', value: percent(metric('slot_accuracy')) },
    { label: '未知召回率', value: percent(metric('unknown_recall')) },
    { label: '平均耗时', value: metric('average_latency_ms') == null ? '-' : `${metric('average_latency_ms')} ms` },
  ];
});

async function loadBenchmarks() {
  benchmarkLoading.value = true;
  try {
    const [datasets, runs] = await Promise.all([listBenchmarkDatasets(), listBenchmarkRuns()]);
    benchmarkDatasets.value = datasets;
    benchmarkRuns.value = runs;
    if (!selectedDatasetId.value && datasets[0]) selectedDatasetId.value = datasets[0].id;
    const running = runs.find((item) => ['queued', 'running'].includes(item.status));
    if (running) {
      activeBenchmarkRun.value = running;
      startBenchmarkPolling(running.run_id);
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '离线基准评测加载失败';
  } finally {
    benchmarkLoading.value = false;
  }
}

async function startOfflineBenchmark() {
  if (!selectedDatasetId.value) return;
  benchmarkStarting.value = true;
  error.value = '';
  try {
    const run = await startBenchmarkRun(selectedDatasetId.value);
    activeBenchmarkRun.value = run;
    toast.value = `已启动：${run.dataset_name}`;
    window.setTimeout(() => { toast.value = ''; }, 3000);
    startBenchmarkPolling(run.run_id);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '离线基准评测启动失败';
  } finally {
    benchmarkStarting.value = false;
  }
}

function startBenchmarkPolling(runId: string) {
  stopBenchmarkPolling();
  const poll = async () => {
    try {
      const run = await getBenchmarkRun(runId);
      activeBenchmarkRun.value = run;
      if (['queued', 'running'].includes(run.status)) {
        benchmarkTimer = window.setTimeout(poll, 1500);
      } else {
        await loadBenchmarks();
      }
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : '评测状态查询失败';
      stopBenchmarkPolling();
    }
  };
  benchmarkTimer = window.setTimeout(poll, 500);
}

function stopBenchmarkPolling() {
  if (benchmarkTimer !== undefined) window.clearTimeout(benchmarkTimer);
  benchmarkTimer = undefined;
}

async function loadEvaluationRuns() {
  runsLoading.value = true;
  try {
    const result = await listEvaluationRuns();
    releaseRuns.value = result.records;
    if (result.records[0]) {
      expandedRunId.value = result.records[0].id;
      await loadRunResults(result.records[0].id);
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '自动验收批次加载失败';
  } finally {
    runsLoading.value = false;
  }
}

async function loadGeneratedCases() {
  casesLoading.value = true;
  error.value = '';
  try {
    const query = new URLSearchParams({ page: '1', size: '100' });
    if (caseStatus.value) query.set('status', caseStatus.value);
    const firstPage = await listEvaluationCases(query);
    const remainingPages = Math.ceil(firstPage.total / 100);
    const remainingRecords = remainingPages > 1
      ? await Promise.all(Array.from({ length: remainingPages - 1 }, (_, index) => {
        const pageQuery = new URLSearchParams(query);
        pageQuery.set('page', String(index + 2));
        return listEvaluationCases(pageQuery);
      }))
      : [];
    generatedCases.value = [firstPage.records, ...remainingRecords.map((item) => item.records)].flat();
    generatedCaseTotal.value = firstPage.total;
    caseGroupPage.value = 1;
    const firstCase = generatedCases.value[0];
    const firstGroup = firstCase
      ? `${firstCase.knowledgeCode}:${firstCase.versionId}`
      : undefined;
    if (firstGroup && !expandedCaseGroupKeys.value.length) expandedCaseGroupKeys.value = [firstGroup];
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '测试集加载失败';
  } finally {
    casesLoading.value = false;
  }
}

async function toggleCaseGroup(key: string) {
  expandedCaseGroupKeys.value = expandedCaseGroupKeys.value.includes(key)
    ? expandedCaseGroupKeys.value.filter((item) => item !== key)
    : [...expandedCaseGroupKeys.value, key];
  if (expandedCaseGroupKeys.value.includes(key)) {
    const group = generatedCaseGroups.value.find((item) => item.key === key);
    const run = group && releaseRuns.value.find((item) => item.versionId === group.versionId);
    if (run) await loadRunResults(run.id);
  }
}

function caseGroupExpanded(key: string) {
  return expandedCaseGroupKeys.value.includes(key);
}

function changeCaseGroupPage(nextPage: number) {
  if (nextPage < 1 || nextPage > caseGroupTotalPages.value) return;
  caseGroupPage.value = nextPage;
  const firstGroup = pagedCaseGroups.value[0];
  if (firstGroup && !expandedCaseGroupKeys.value.includes(firstGroup.key)) {
    void toggleCaseGroup(firstGroup.key);
  }
}

async function toggleRun(item: EvaluationRunItem) {
  expandedRunId.value = item.id;
  await loadRunResults(item.id);
}

async function loadRunResults(runId: number) {
  if (runResults.value[runId] || runResultsLoadingId.value === runId) return;
  runResultsLoadingId.value = runId;
  try {
    runResults.value = { ...runResults.value, [runId]: await listEvaluationRunResults(runId) };
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '验收用例明细加载失败';
  } finally {
    runResultsLoadingId.value = null;
  }
}

function caseStatusLabel(value: number) {
  return ['待知识审批', '待自动验收', '已驳回', '已生效'][value] || '未知';
}

function caseStatusClass(value: number) {
  return value === 3 ? 'published' : value === 2 ? 'rejected' : 'pending';
}

function runStatusLabel(value: number) {
  return ['待执行', '执行中', '通过', '未通过', '系统失败'][value] || '未知';
}

function runStatusClass(value: number) {
  return value === 2 ? 'published' : value >= 3 ? 'rejected' : 'pending';
}

function percent(value?: number) {
  return value == null ? '-' : `${(value * 100).toFixed(2)}%`;
}

function runMetric(item: EvaluationRunItem) {
  if (item.recallAt1 == null) return item.errorMessage || '等待自动执行';
  return `R@1 ${percent(item.recallAt1)} · 阈值召回 ${percent(item.thresholdRecall)} · 负样本误命中 ${percent(item.hardNegativeFalsePositiveRate)}`;
}

function thresholdPassedCount(item: EvaluationRunItem) {
  return Math.round((item.thresholdRecall || 0) * item.positiveCases);
}

function runFailureReason(item: EvaluationRunItem) {
  if (item.status === 4) return item.errorMessage || '执行器发生系统错误';
  const reasons: string[] = [];
  if ((item.recallAt1 || 0) < 0.8) reasons.push('R@1 未达到 80%');
  if ((item.recallAt3 || 0) < 1) reasons.push('R@3 未达到 100%');
  if ((item.thresholdRecall || 0) < 0.8) reasons.push(`阈值召回未达标，${item.positiveCases} 条正样本仅 ${thresholdPassedCount(item)} 条在 ${item.distanceThreshold ?? 0.38} 阈值内`);
  if ((item.hardNegativeFalsePositiveRate || 0) > 0) reasons.push('存在困难负样本误命中');
  if ((item.errorCount || 0) > 0) reasons.push(`${item.errorCount} 条用例执行异常`);
  return reasons.join('；') || '所有发布门槛均已满足';
}

function resultLabel(item: EvaluationRunCaseResultItem) {
  if (item.errorMessage) return '执行异常';
  if (item.expectedMatch) return item.passedThreshold ? '可信命中' : '距离超阈值';
  return item.passedThreshold ? '正确拒绝' : '负样本误命中';
}

function resultForCase(caseId: number) {
  return allRunResultsByCaseId.value.get(caseId);
}

function runForCase(item: EvaluationCaseItem) {
  return releaseRuns.value.find((run) => run.versionId === item.versionId);
}

function caseEvaluationLabel(item: EvaluationCaseItem) {
  const result = resultForCase(item.id);
  if (!result) return caseStatusLabel(item.status);
  if (result.errorMessage) return '执行异常';
  return result.passedThreshold ? '本条通过' : '本条未通过';
}

function caseEvaluationClass(item: EvaluationCaseItem) {
  const result = resultForCase(item.id);
  if (!result) return caseStatusClass(item.status);
  return result.passedThreshold ? 'published' : 'rejected';
}

function caseFailureReason(item: EvaluationCaseItem) {
  const result = resultForCase(item.id);
  const run = runForCase(item);
  if (!result || result.passedThreshold) return '';
  if (result.errorMessage) return result.errorMessage;
  const distance = result.topDistance == null ? '-' : result.topDistance.toFixed(6);
  const threshold = run?.distanceThreshold ?? 0.38;
  return item.expectedMatch
    ? `目标知识虽排第 1，但距离 ${distance} 超过门槛 ${threshold}`
    : `困难负样本距离 ${distance} 进入门槛 ${threshold}，发生误命中`;
}

function benchmarkStatusLabel(value: BenchmarkRun['status']) {
  return ({ queued: '等待执行', running: '执行中', completed: '已完成', passed: '已通过', failed: '未通过', system_failed: '系统失败' } as Record<BenchmarkRun['status'], string>)[value];
}

function benchmarkStatusClass(value: BenchmarkRun['status']) {
  return value === 'passed' || value === 'completed' ? 'published' : value === 'failed' || value === 'system_failed' ? 'rejected' : 'pending';
}

function benchmarkIsActive(run?: BenchmarkRun | null) {
  return !!run && ['queued', 'running'].includes(run.status);
}

function benchmarkSummary(run: BenchmarkRun) {
  if (run.status === 'queued') return '任务已进入执行队列，正在准备评测环境。';
  if (run.status === 'running') return `正在运行 ${run.case_count} 条样本，完成后会自动更新指标和报告。`;
  if (run.status === 'system_failed') return run.error_message || '执行器发生系统错误。';
  const failedChecks = run.acceptance?.checks?.filter((item) => !item.passed) || [];
  if (failedChecks.length) return `未达标：${failedChecks.map((item) => `${item.metric} ${item.actual}`).join('；')}`;
  return run.status === 'completed' ? '数据集未配置验收门槛，本次评测已完成。' : `本次 ${run.case_count} 条样本评测${run.status === 'passed' ? '达到' : '未达到'}数据集门槛。`;
}

function benchmarkDownloadName(run: BenchmarkRun, format: 'json' | 'markdown') {
  const type = run.evaluation_type === 'retrieval' ? '知识召回' : '意图识别';
  const status = benchmarkStatusLabel(run.status);
  const completed = new Date(run.finished_at || run.started_at || run.created_at);
  const timestamp = [
    completed.getFullYear(),
    String(completed.getMonth() + 1).padStart(2, '0'),
    String(completed.getDate()).padStart(2, '0'),
    '-',
    String(completed.getHours()).padStart(2, '0'),
    String(completed.getMinutes()).padStart(2, '0'),
    String(completed.getSeconds()).padStart(2, '0'),
  ].join('');
  const safeDatasetName = run.dataset_name.replace(/[\\/:*?"<>|\s]+/g, '_');
  return `${safeDatasetName}_${type}_${run.case_count}条_${status}_${timestamp}.${format === 'json' ? 'json' : 'md'}`;
}

async function downloadBenchmarkReport(run: BenchmarkRun, format: 'json' | 'markdown') {
  try {
    const response = await fetch(benchmarkReportUrl(run.run_id, format));
    if (!response.ok) throw new Error(`报告下载失败：${response.status}`);
    const objectUrl = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = benchmarkDownloadName(run, format);
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '报告下载失败';
  }
}

function categoryLabel(value: string) {
  return ({ conversational: '口语', omitted: '省略', typo: '错别字', inverted: '倒装/追问', boundary: '边界', hard_negative: '困难负样本' } as Record<string, string>)[value] || value;
}

function formatTime(value?: string) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-';
}
</script>

<template>
  <main class="kb-main evaluation-view">
    <header class="kb-header">
      <div><h1>评测中心</h1><p>管理意图识别、知识召回、负样本和自动验收门槛</p></div>
      <label class="operator-field">操作人 ID<input v-model="operatorId" maxlength="64" /></label>
    </header>

    <div v-if="toast" class="kb-notice success"><Check :size="17" />{{ toast }}</div>
    <div v-if="error" class="kb-notice error"><CircleAlert :size="17" />{{ error }}</div>

    <section class="evaluation-section generated-cases-section numbered-section">
      <header><div class="section-heading"><span class="section-number">1</span><div><h2>问题学习测试集</h2><p>全部知识草稿生成的测试用例，按“知识 + 版本”分组展示</p></div></div><div class="case-toolbar"><select v-model="caseStatus" aria-label="测试用例状态" @change="loadGeneratedCases"><option value="">全部状态</option><option value="0">待知识审批</option><option value="1">待自动验收</option><option value="2">已驳回</option><option value="3">已生效</option></select><button class="icon-command" type="button" title="刷新测试集" :disabled="casesLoading" @click="loadGeneratedCases"><RefreshCw :class="{ spin: casesLoading }" :size="17" /></button></div></header>
      <div class="scope-explanation"><strong>{{ generatedCaseGroups.length }}</strong> 个知识草稿版本<span>{{ generatedCaseTotal }} 条测试用例；展开一组可查看该版本自己的正样本和困难负样本</span></div>
      <div v-if="casesLoading" class="empty"><LoaderCircle class="spin" :size="17" />正在加载</div>
      <div v-else-if="!generatedCaseGroups.length" class="empty">暂无问题学习测试用例</div>
      <div v-else class="case-group-list">
        <article v-for="group in pagedCaseGroups" :key="group.key" class="case-group" :class="{ expanded: caseGroupExpanded(group.key) }">
          <button class="case-group-summary" type="button" :aria-expanded="caseGroupExpanded(group.key)" @click="toggleCaseGroup(group.key)">
            <ChevronDown v-if="caseGroupExpanded(group.key)" :size="18" /><ChevronRight v-else :size="18" />
            <span class="case-group-title"><strong>{{ group.knowledgeTitle }}</strong><small>{{ group.knowledgeCode }} · V{{ group.versionNo }} · {{ group.problemCode }}</small></span>
            <span class="case-group-count"><strong>{{ group.cases.length }}</strong><small>总用例</small></span>
            <span class="case-group-count positive"><strong>{{ group.positiveCases }}</strong><small>正样本</small></span>
            <span class="case-group-count negative"><strong>{{ group.hardNegativeCases }}</strong><small>困难负样本</small></span>
            <span class="status" :class="caseStatusClass(group.status)">批次{{ caseStatusLabel(group.status) }}</span>
          </button>
          <div v-if="caseGroupExpanded(group.key)" class="kb-table-scroll case-group-detail">
            <table class="evaluation-table generated-cases"><thead><tr><th>测试问法</th><th>类别</th><th>预期结果</th><th>难度</th><th>单条评测结果</th><th>生成模型</th></tr></thead><tbody><tr v-for="item in group.cases" :key="item.id"><td><strong>{{ item.questionText }}</strong><small>{{ item.caseCode }}</small></td><td>{{ categoryLabel(item.caseCategory) }}</td><td><span class="expectation" :class="item.expectedMatch ? 'match' : 'reject'">{{ item.expectedMatch ? '应命中该知识' : '不应命中该知识' }}</span></td><td>难度 {{ item.difficulty }}</td><td class="case-result-cell"><span class="status" :class="caseEvaluationClass(item)">{{ caseEvaluationLabel(item) }}</span><small v-if="caseFailureReason(item)" class="case-failure-reason">{{ caseFailureReason(item) }}</small></td><td>{{ item.generatedModel }}</td></tr></tbody></table>
          </div>
        </article>
      </div>
      <footer class="case-group-pagination"><span>第 {{ caseGroupPage }} / {{ caseGroupTotalPages }} 页 · 每页 {{ caseGroupsPerPage }} 个知识版本</span><button type="button" title="上一页" :disabled="caseGroupPage <= 1" @click="changeCaseGroupPage(caseGroupPage - 1)"><ChevronLeft :size="17" /></button><button type="button" title="下一页" :disabled="caseGroupPage >= caseGroupTotalPages" @click="changeCaseGroupPage(caseGroupPage + 1)"><ChevronRight :size="17" /></button></footer>
    </section>

    <section class="evaluation-section release-evaluation-section numbered-section">
      <header><div class="section-heading"><span class="section-number">2</span><div><h2>知识发布自动验收</h2><p>每个候选知识版本独立计算；这里不是所有知识草稿的汇总结果</p></div></div><button class="icon-command" type="button" title="刷新自动验收" :disabled="runsLoading" @click="loadEvaluationRuns"><RefreshCw :class="{ spin: runsLoading }" :size="17" /></button></header>
      <template v-if="selectedRun">
        <div class="latest-run-heading"><div><span>最近一次验收</span><strong>{{ selectedRun.knowledgeTitle }}</strong><small>{{ selectedRun.runNo }} · {{ selectedRun.knowledgeCode }} · {{ selectedRun.totalCases }} 条用例</small></div><div class="latest-run-state"><span class="status" :class="runStatusClass(selectedRun.status)">{{ runStatusLabel(selectedRun.status) }}</span><small><Clock3 :size="14" />{{ formatTime(selectedRun.finishedAt || selectedRun.startedAt || selectedRun.createdAt) }}</small></div></div>
        <div class="release-gate-strip" aria-label="自动发布验收门槛">
          <div v-for="gate in releaseGateRows" :key="gate.label" :class="gate.passed ? 'passed' : 'failed'">
            <span>{{ gate.label }}</span><strong>{{ gate.value }}</strong><small>{{ gate.detail }}</small><em><Check v-if="gate.passed" :size="14" /><CircleAlert v-else :size="14" />{{ gate.requirement }} · {{ gate.passed ? '通过' : '未通过' }}</em>
          </div>
        </div>
        <div v-if="selectedRun.status >= 3" class="run-failure-explanation"><CircleAlert :size="19" /><div><strong>{{ selectedRun.status === 4 ? '系统执行失败' : '未通过原因' }}</strong><p>{{ runFailureReason(selectedRun) }}</p></div></div>
        <div class="run-case-results">
          <header><div><strong>逐条结果</strong><span>仅突出显示未通过或执行异常的用例</span></div><span>{{ failedRunCases.length }} 条需要处理</span></header>
          <div v-if="runResultsLoadingId === selectedRun.id" class="run-results-loading"><LoaderCircle class="spin" :size="17" />正在加载用例明细</div>
          <div v-else-if="!failedRunCases.length" class="run-results-empty"><Check :size="17" />没有失败用例</div>
          <div v-else class="kb-table-scroll"><table class="evaluation-table failed-cases"><thead><tr><th>测试问法</th><th>样本类型</th><th>第一名结果</th><th>实际距离</th><th>判定</th></tr></thead><tbody><tr v-for="item in failedRunCases" :key="item.caseId"><td><strong>{{ item.questionText }}</strong><small>{{ item.caseCode }} · {{ categoryLabel(item.caseCategory) }}</small></td><td>{{ item.expectedMatch ? '正样本 · 应命中' : '困难负样本 · 不应命中' }}</td><td>{{ item.passedAt1 ? '目标知识排第 1' : '第一名不是目标知识' }}</td><td><strong>{{ item.topDistance == null ? '-' : item.topDistance.toFixed(6) }}</strong><small>门槛 ≤ {{ selectedRun.distanceThreshold ?? 0.38 }}</small></td><td><span class="result-failed">{{ resultLabel(item) }}</span></td></tr></tbody></table></div>
        </div>
      </template>
      <div v-else class="empty">暂无自动发布验收记录</div>
      <div class="run-history-heading"><div><strong>独立运行历史</strong><span>每一行只代表一个候选知识版本的验收结果</span></div></div>
      <div class="kb-table-scroll"><table class="evaluation-table history"><thead><tr><th>候选知识 / 运行编号</th><th>样本组成</th><th>核心结果</th><th>状态</th><th>运行时间</th><th>操作</th></tr></thead><tbody><tr v-if="runsLoading"><td colspan="6" class="empty"><LoaderCircle class="spin" :size="17" />正在加载</td></tr><tr v-else-if="!releaseRuns.length"><td colspan="6" class="empty">暂无自动发布验收记录</td></tr><tr v-for="item in releaseRuns" v-else :key="item.id" :class="{ 'selected-run-row': selectedRun?.id === item.id }"><td><strong>{{ item.knowledgeTitle }}</strong><small>{{ item.runNo }} · {{ item.knowledgeCode }}</small></td><td>{{ item.totalCases }} 条<small>{{ item.positiveCases }} 正样本 · {{ item.hardNegativeCases }} 困难负样本</small></td><td>{{ runMetric(item) }}</td><td><span class="status" :class="runStatusClass(item.status)">{{ runStatusLabel(item.status) }}</span></td><td>{{ formatTime(item.finishedAt || item.startedAt || item.createdAt) }}</td><td><button class="run-detail-command" type="button" @click="toggleRun(item)">{{ selectedRun?.id === item.id ? '正在查看' : '查看明细' }}</button></td></tr></tbody></table></div>
    </section>

    <section class="evaluation-section offline-benchmark-section numbered-section">
      <header><div class="section-heading"><span class="section-number">3</span><div><h2>离线基准评测</h2><p>选择固定数据集后启动 Python 全量评测，与单个知识版本的发布验收互不混合</p></div></div><button class="icon-command" type="button" title="刷新离线评测" :disabled="benchmarkLoading" @click="loadBenchmarks"><RefreshCw :class="{ spin: benchmarkLoading }" :size="17" /></button></header>
      <div class="benchmark-command-panel">
        <label>评测数据集<select v-model="selectedDatasetId" :disabled="benchmarkIsActive(latestBenchmarkRun)"><option v-for="item in benchmarkDatasets" :key="item.id" :value="item.id">{{ item.name }} · {{ item.case_count }}条 · {{ item.evaluation_type === 'retrieval' ? '知识召回' : '意图识别' }}</option></select></label>
        <div class="benchmark-dataset-copy"><strong>{{ selectedDataset?.name || '请选择数据集' }}</strong><p>{{ selectedDataset?.description || '加载数据集目录中' }}</p></div>
        <button class="primary-command" type="button" :disabled="benchmarkStarting || benchmarkLoading || benchmarkIsActive(latestBenchmarkRun) || !selectedDatasetId" @click="startOfflineBenchmark"><LoaderCircle v-if="benchmarkStarting || benchmarkIsActive(latestBenchmarkRun)" class="spin" :size="17" /><TrendingUp v-else :size="17" />{{ benchmarkIsActive(latestBenchmarkRun) ? '评测执行中' : '开始评测' }}</button>
      </div>

      <div v-if="latestBenchmarkRun" class="evaluation-status" :class="latestBenchmarkRun.status === 'passed' || latestBenchmarkRun.status === 'completed' ? 'passed' : 'failed'">
        <LoaderCircle v-if="benchmarkIsActive(latestBenchmarkRun)" class="spin" :size="20" /><Check v-else-if="latestBenchmarkRun.status === 'passed' || latestBenchmarkRun.status === 'completed'" :size="20" /><CircleAlert v-else :size="20" />
        <div><strong>{{ latestBenchmarkRun.dataset_name }} · {{ benchmarkStatusLabel(latestBenchmarkRun.status) }}</strong><p>{{ benchmarkSummary(latestBenchmarkRun) }}</p></div>
        <div class="benchmark-report-links"><a v-if="latestBenchmarkRun.json_report_name" :href="benchmarkReportUrl(latestBenchmarkRun.run_id, 'json')" :download="benchmarkDownloadName(latestBenchmarkRun, 'json')" @click.prevent="downloadBenchmarkReport(latestBenchmarkRun, 'json')"><FileJson :size="15" />JSON</a><a v-if="latestBenchmarkRun.markdown_report_name" :href="benchmarkReportUrl(latestBenchmarkRun.run_id, 'markdown')" :download="benchmarkDownloadName(latestBenchmarkRun, 'markdown')" @click.prevent="downloadBenchmarkReport(latestBenchmarkRun, 'markdown')"><FileJson :size="15" />Markdown</a><span><Clock3 :size="15" />{{ formatTime(latestBenchmarkRun.finished_at || latestBenchmarkRun.started_at || latestBenchmarkRun.created_at) }}</span></div>
      </div>

      <div v-if="benchmarkMetricRows.length" class="metric-strip benchmark-metrics" aria-label="离线基准评测指标"><div v-for="metric in benchmarkMetricRows" :key="metric.label"><span>{{ metric.label }}</span><strong>{{ metric.value }}</strong></div></div>
      <div class="kb-table-scroll"><table class="evaluation-table benchmark-history"><thead><tr><th>数据集</th><th>类型</th><th>样本数</th><th>状态</th><th>完成时间</th><th>报告文件</th></tr></thead><tbody><tr v-if="benchmarkLoading"><td colspan="6" class="empty"><LoaderCircle class="spin" :size="17" />正在加载</td></tr><tr v-else-if="!benchmarkRuns.length"><td colspan="6" class="empty">暂无离线基准评测记录</td></tr><tr v-for="item in benchmarkRuns" v-else :key="item.run_id"><td><strong>{{ item.dataset_name }}</strong><small>{{ item.run_id.slice(0, 12) }}</small></td><td>{{ item.evaluation_type === 'retrieval' ? '知识召回' : '意图识别' }}</td><td>{{ item.case_count }}</td><td><span class="status" :class="benchmarkStatusClass(item.status)">{{ benchmarkStatusLabel(item.status) }}</span></td><td>{{ formatTime(item.finished_at || item.started_at || item.created_at) }}</td><td><div class="table-report-actions"><a v-if="item.json_report_name" class="table-report-link" :href="benchmarkReportUrl(item.run_id, 'json')" :download="benchmarkDownloadName(item, 'json')" @click.prevent="downloadBenchmarkReport(item, 'json')"><FileJson :size="14" />JSON</a><a v-if="item.markdown_report_name" class="table-report-link" :href="benchmarkReportUrl(item.run_id, 'markdown')" :download="benchmarkDownloadName(item, 'markdown')" @click.prevent="downloadBenchmarkReport(item, 'markdown')"><FileJson :size="14" />MD</a><span v-if="!item.json_report_name && !item.markdown_report_name">-</span></div></td></tr></tbody></table></div>
    </section>
  </main>
</template>
