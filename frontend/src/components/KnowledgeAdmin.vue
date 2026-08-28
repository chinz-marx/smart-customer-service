<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import {
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  FileClock,
  FlaskConical,
  Inbox,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Save,
  Settings,
  Trash2,
  X,
} from '@lucide/vue';
import EvaluationCenterView from './EvaluationCenterView.vue';
import KnowledgeChunkEditor from './KnowledgeChunkEditor.vue';
import ProblemCollectionView from './ProblemCollectionView.vue';
import {
  knowledgeApi,
  type ApprovalListItem,
  type Category,
  type KnowledgeDetail,
  type KnowledgeFormPayload,
  type KnowledgeListItem,
} from '../services/knowledgeApi';
import '../knowledge-admin.css';
import '../admin-operations.css';

type ViewName = 'all' | 'pending' | 'published' | 'disabled';
type AdminModule = 'knowledge' | 'problems' | 'evaluation';

/** 页面草稿只使用临时 ID，提交数据库时由后端生成正式主键。 */
interface QuestionDraft {
  id: number;
  text: string;
}

interface ChunkDraft {
  id: number;
  content: string;
  questions: QuestionDraft[];
}

const categories = ref<Category[]>([]);
const rows = ref<KnowledgeListItem[]>([]);
const approvals = ref<ApprovalListItem[]>([]);
const total = ref(0);
const page = ref(1);
const size = 15;
const keyword = ref('');
const categoryId = ref('');
const view = ref<ViewName>('all');
const loading = ref(false);
const drawerOpen = ref(false);
const saving = ref(false);
const savingDraft = ref(false);
const approvalProcessingId = ref<number | null>(null);
const rejectingKnowledgeId = ref<number | null>(null);
const rejectionReason = ref('');
const editingId = ref<number | null>(null);
const detail = ref<KnowledgeDetail | null>(null);
const toast = ref('');
const error = ref('');
const operatorId = ref(localStorage.getItem('kb-operator-id') || 'reviewer-001');
const activeModule = ref<AdminModule>(moduleFromHash());
const chunkDrafts = ref<ChunkDraft[]>([]);

const form = reactive({
  title: '',
  categoryId: '',
  content: '',
  tags: '',
  intentCode: '',
  effectiveAt: '',
  expiredAt: '',
  applicationReason: '',
});

const tabs: { value: ViewName; label: string }[] = [
  { value: 'all', label: '全部知识' },
  { value: 'pending', label: '待审批' },
  { value: 'published', label: '已发布' },
  { value: 'disabled', label: '已停用' },
];

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size)));
const drawerTitle = computed(() => editingId.value ? '编辑知识' : '新增知识');
const visibleVersion = computed(() => detail.value?.pendingVersion || detail.value?.currentVersion);
const approvalLocked = computed(() => Boolean(
  detail.value?.pendingVersion && detail.value.pendingVersion.versionStatus !== 0,
));

onMounted(async () => {
  window.addEventListener('hashchange', syncModuleFromHash);
  await Promise.all([loadCategories(), loadRows(), loadApprovals()]);
});

onBeforeUnmount(() => window.removeEventListener('hashchange', syncModuleFromHash));

watch(operatorId, (value) => localStorage.setItem('kb-operator-id', value.trim()));
watch([view, categoryId], () => {
  page.value = 1;
  void loadRows();
});

async function loadCategories() {
  try {
    categories.value = await knowledgeApi.categories();
  } catch (cause) {
    showError(cause);
  }
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const query = new URLSearchParams({ page: String(page.value), size: String(size), view: view.value });
    if (keyword.value.trim()) query.set('keyword', keyword.value.trim());
    if (categoryId.value) query.set('categoryId', categoryId.value);
    const result = await knowledgeApi.list(query);
    rows.value = result.records;
    total.value = result.total;
  } catch (cause) {
    showError(cause);
  } finally {
    loading.value = false;
  }
}

async function loadApprovals() {
  try {
    approvals.value = (await knowledgeApi.approvals(1, 100)).records;
  } catch (cause) {
    showError(cause);
  }
}

function openCreate() {
  editingId.value = null;
  detail.value = null;
  chunkDrafts.value = [];
  Object.assign(form, {
    title: '', categoryId: categories.value[0]?.id ? String(categories.value[0].id) : '',
    content: '', tags: '', intentCode: '',
    effectiveAt: toLocalInput(new Date().toISOString()), expiredAt: '', applicationReason: '',
  });
  drawerOpen.value = true;
}

async function openEdit(id: number) {
  try {
    detail.value = await knowledgeApi.detail(id);
    editingId.value = id;
    const version = detail.value.pendingVersion || detail.value.currentVersion;
    if (!version) throw new Error('知识版本不存在');
    Object.assign(form, {
      title: version.title,
      categoryId: String(detail.value.knowledge.categoryId),
      content: version.content,
      tags: (version.tags || []).join(', '),
      intentCode: version.intentCode || '',
      effectiveAt: toLocalInput(version.effectiveAt),
      expiredAt: toLocalInput(version.expiredAt),
      applicationReason: detail.value.latestApproval?.applicationReason || '',
    });
    // 编辑时回显当前待审批版本（没有待审批版本时回显已发布版本）的分片与问法。
    chunkDrafts.value = detail.value.chunks.map((chunk, chunkIndex) => ({
      id: chunk.id ?? Date.now() * 100 + chunkIndex,
      content: chunk.content,
      questions: chunk.questions.map((question, questionIndex) => ({
        id: (chunk.id ?? Date.now()) * 100 + questionIndex,
        text: question,
      })),
    }));
    drawerOpen.value = true;
  } catch (cause) {
    showError(cause);
  }
}

function buildKnowledgePayload(): KnowledgeFormPayload | null {
  if (!operatorId.value.trim()) {
    showError(new Error('请填写操作人 ID'));
    return null;
  }
  if (!form.title.trim() || !form.content.trim() || !form.categoryId || !form.effectiveAt) {
    showError(new Error('请填写标题、分类、内容和生效时间'));
    return null;
  }
  if (!chunkDrafts.value.length) {
    showError(new Error('请先生成或新增至少一个原子分片'));
    return null;
  }
  if (chunkDrafts.value.some((chunk) =>
    !chunk.content.trim()
      || !chunk.questions.length
      || chunk.questions.some((question) => !question.text.trim()))) {
    showError(new Error('每个原子分片都必须填写内容，并至少保留一个完整的标准问法'));
    return null;
  }
  return {
    title: form.title.trim(),
    categoryId: Number(form.categoryId),
    content: form.content.trim(),
    tags: form.tags.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
    intentCode: form.intentCode.trim() || undefined,
    effectiveAt: new Date(form.effectiveAt).toISOString(),
    expiredAt: form.expiredAt ? new Date(form.expiredAt).toISOString() : undefined,
    applicationReason: form.applicationReason.trim() || undefined,
    // 只提交业务字段，页面临时 ID 不进入数据库。
    chunks: chunkDrafts.value.map((chunk) => ({
      content: chunk.content.trim(),
      questions: chunk.questions.map((question) => question.text.trim()),
    })),
  };
}

async function saveKnowledge() {
  const payload = buildKnowledgePayload();
  if (!payload) return;
  saving.value = true;
  try {
    if (editingId.value) {
      await knowledgeApi.update(editingId.value, payload, operatorId.value.trim());
    } else {
      await knowledgeApi.create(payload, operatorId.value.trim());
    }
    drawerOpen.value = false;
    notify('已提交审批，审批通过后才会发布到 Redis Search');
    await Promise.all([loadRows(), loadApprovals()]);
  } catch (cause) {
    showError(cause);
  } finally {
    saving.value = false;
  }
}

async function saveKnowledgeDraft() {
  if (!editingId.value) return;
  const payload = buildKnowledgePayload();
  if (!payload) return;
  savingDraft.value = true;
  try {
    detail.value = await knowledgeApi.saveDraft(
      editingId.value,
      payload,
      operatorId.value.trim(),
    );
    notify('草稿已保存，尚未提交审批');
    await loadRows();
  } catch (cause) {
    showError(cause);
  } finally {
    savingDraft.value = false;
  }
}

async function requestDisable(row: KnowledgeListItem) {
  if (!confirm(`确定提交“${row.title}”的停用审批吗？`)) return;
  try {
    await knowledgeApi.disable(row.id, operatorId.value.trim());
    notify('停用申请已提交');
    await Promise.all([loadRows(), loadApprovals()]);
  } catch (cause) {
    showError(cause);
  }
}

async function approve(item: ApprovalListItem) {
  if (!operatorId.value.trim()) return showError(new Error('请填写操作人 ID'));
  if (isSelfApproval(item)) return showError(new Error(selfApprovalMessage(item)));
  approvalProcessingId.value = item.approvalId;
  try {
    await knowledgeApi.approve(item.approvalId, operatorId.value.trim(), '后台人工审核通过');
    notify('审批已通过，索引发布任务已进入队列');
    await Promise.all([loadRows(), loadApprovals()]);
  } catch (cause) {
    showError(cause);
  } finally {
    approvalProcessingId.value = null;
  }
}

function beginReject(item: ApprovalListItem) {
  if (isSelfApproval(item)) return showError(new Error(selfApprovalMessage(item)));
  rejectingKnowledgeId.value = item.knowledgeId;
  rejectionReason.value = '';
}

function cancelReject() {
  rejectingKnowledgeId.value = null;
  rejectionReason.value = '';
}

async function confirmReject(item: ApprovalListItem) {
  if (!operatorId.value.trim()) return showError(new Error('请填写操作人 ID'));
  if (isSelfApproval(item)) return showError(new Error(selfApprovalMessage(item)));
  if (!rejectionReason.value.trim()) return showError(new Error('请输入驳回原因'));
  approvalProcessingId.value = item.approvalId;
  try {
    await knowledgeApi.reject(
      item.approvalId,
      operatorId.value.trim(),
      rejectionReason.value.trim(),
    );
    cancelReject();
    notify('审批已驳回');
    await Promise.all([loadRows(), loadApprovals()]);
  } catch (cause) {
    showError(cause);
  } finally {
    approvalProcessingId.value = null;
  }
}

function approvalFor(knowledgeId: number): ApprovalListItem | undefined {
  return approvals.value.find((item) => item.knowledgeId === knowledgeId);
}

function isSelfApproval(item?: ApprovalListItem): boolean {
  return Boolean(item && operatorId.value.trim() === item.applicantId);
}

function selfApprovalMessage(item: ApprovalListItem): string {
  return `当前操作人 ${operatorId.value.trim()} 是该申请的申请人，请切换其他操作人审批`;
}

async function showApprovalRows() {
  activeModule.value = 'knowledge';
  window.location.hash = '#/knowledge';
  view.value = 'pending';
  page.value = 1;
  await Promise.all([loadRows(), loadApprovals()]);
}

function changePage(next: number) {
  if (next < 1 || next > totalPages.value) return;
  page.value = next;
  void loadRows();
}

function statusLabel(row: KnowledgeListItem) {
  if (row.versionStatus === 0) return '草稿';
  if (row.versionStatus === 1) return '待审批';
  if (row.versionStatus === 3) return '已驳回';
  return row.status === 1 ? '已发布' : '已停用';
}

function statusClass(row: KnowledgeListItem) {
  if (row.versionStatus === 0) return 'draft';
  if (row.versionStatus === 1) return 'pending';
  if (row.versionStatus === 3) return 'rejected';
  return row.status === 1 ? 'published' : 'disabled';
}

function formatDate(value?: string) {
  return value ? new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value)) : '-';
}

function toLocalInput(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function notify(message: string) {
  toast.value = message;
  error.value = '';
  window.setTimeout(() => { if (toast.value === message) toast.value = ''; }, 3500);
}

function showError(cause: unknown) {
  error.value = cause instanceof Error ? cause.message : '操作失败，请稍后重试';
}

// hash地址支持刷新和浏览器前进后退，同时不引入额外路由依赖。
function moduleFromHash(): AdminModule {
  if (window.location.hash.startsWith('#/knowledge/problems')) return 'problems';
  if (window.location.hash.startsWith('#/knowledge/evaluation')) return 'evaluation';
  return 'knowledge';
}

function syncModuleFromHash() {
  activeModule.value = moduleFromHash();
}

function switchModule(module: AdminModule) {
  activeModule.value = module;
  window.location.hash = module === 'knowledge' ? '#/knowledge' : '#/knowledge/' + module;
}
</script>

<template>
  <div class="kb-app">
    <aside class="kb-sidebar">
      <div class="kb-brand"><BookOpen :size="22" /><strong>智服知识台</strong></div>
      <nav>
        <a href="#/knowledge" :class="{ active: activeModule === 'knowledge' }" @click="switchModule('knowledge')"><BookOpen :size="18" />知识管理</a>
        <button type="button" :class="{ active: activeModule === 'problems' }" @click="switchModule('problems')"><Inbox :size="18" />问题收集</button>
        <button type="button" :class="{ active: activeModule === 'evaluation' }" @click="switchModule('evaluation')"><FlaskConical :size="18" />评测中心</button>
        <button type="button" :class="{ active: activeModule === 'knowledge' && view === 'pending' }" @click="showApprovalRows"><ClipboardCheck :size="18" />审批中心<span>{{ approvals.length }}</span></button>
        <button type="button"><LayoutDashboard :size="18" />运营概览</button>
        <button type="button"><FileClock :size="18" />操作日志</button>
        <button type="button"><Settings :size="18" />系统设置</button>
      </nav>
      <a class="back-chat" href="#/"><LogOut :size="17" />返回客服端</a>
    </aside>

    <main v-if="activeModule === 'knowledge'" class="kb-main">
      <header class="kb-header">
        <div><h1>知识管理</h1><p>维护 FAQ、活动规则、会员权益、退款规则与订单说明</p></div>
        <label class="operator-field">操作人 ID<input v-model="operatorId" maxlength="64" /></label>
      </header>

      <div v-if="toast" class="kb-notice success"><Check :size="17" />{{ toast }}</div>
      <div v-if="error" class="kb-notice error"><X :size="17" />{{ error }}</div>

      <section class="kb-toolbar" aria-label="知识筛选">
        <div class="kb-search"><Search :size="17" /><input v-model="keyword" placeholder="搜索标题或内容" @keyup.enter="loadRows" /></div>
        <select v-model="categoryId" aria-label="知识分类"><option value="">全部分类</option><option v-for="item in categories" :key="item.id" :value="String(item.id)">{{ item.categoryName }}</option></select>
        <button class="icon-command" type="button" title="刷新" @click="loadRows"><RefreshCw :size="18" /></button>
        <button class="primary-command" type="button" @click="openCreate"><Plus :size="18" />新增知识</button>
      </section>

      <div class="kb-tabs" role="tablist">
        <button v-for="tab in tabs" :key="tab.value" :class="{ active: view === tab.value }" type="button" @click="view = tab.value">{{ tab.label }}</button>
      </div>

      <section class="kb-table-section">
        <div class="table-summary"><strong>{{ total }}</strong> 条知识<span>每次修改都会生成新版本并进入审批</span></div>
        <div class="kb-table-scroll">
          <table>
            <thead><tr><th>标题</th><th>分类</th><th>状态</th><th>版本</th><th>创建时间</th><th>发布时间</th><th>创建人</th><th>最后修改人</th><th>审批人</th><th class="actions">操作</th></tr></thead>
            <tbody>
              <tr v-if="loading"><td colspan="10" class="empty"><LoaderCircle class="spin" :size="22" />正在加载</td></tr>
              <tr v-else-if="!rows.length"><td colspan="10" class="empty">没有符合条件的知识</td></tr>
              <template v-for="row in rows" v-else :key="row.id">
                <tr>
                  <td class="title-cell"><button type="button" @click="openEdit(row.id)">{{ row.title }}</button><small>{{ row.knowledgeCode }}</small></td>
                  <td>{{ row.categoryName }}</td><td><span class="status" :class="statusClass(row)">{{ statusLabel(row) }}</span></td>
                  <td>V{{ row.versionNo }}</td><td>{{ formatDate(row.createdAt) }}</td><td>{{ formatDate(row.publishedAt) }}</td>
                  <td>{{ row.createdBy }}</td><td>{{ row.updatedBy }}</td><td>{{ row.approverId || '-' }}</td>
                  <td class="row-actions">
                    <div class="row-action-buttons">
                      <button title="编辑" type="button" @click="openEdit(row.id)"><Pencil :size="16" /></button>
                      <button title="申请停用" type="button" :disabled="row.status !== 1 || row.versionStatus === 1" @click="requestDisable(row)"><Trash2 :size="16" /></button>
                      <template v-if="view === 'pending' && approvalFor(row.id)">
                        <button class="approval-row-command reject" type="button" :title="isSelfApproval(approvalFor(row.id)) ? selfApprovalMessage(approvalFor(row.id)!) : '驳回'" :disabled="approvalProcessingId === approvalFor(row.id)?.approvalId || isSelfApproval(approvalFor(row.id))" @click="beginReject(approvalFor(row.id)!)"><X :size="14" />驳回</button>
                        <button class="approval-row-command approve" type="button" :title="isSelfApproval(approvalFor(row.id)) ? selfApprovalMessage(approvalFor(row.id)!) : '通过'" :disabled="approvalProcessingId === approvalFor(row.id)?.approvalId || isSelfApproval(approvalFor(row.id))" @click="approve(approvalFor(row.id)!)"><Check :size="14" />通过</button>
                      </template>
                    </div>
                  </td>
                </tr>
                <tr v-if="view === 'pending' && approvalFor(row.id) && isSelfApproval(approvalFor(row.id))" class="self-approval-row">
                  <td colspan="10"><strong>不能审批自己的申请</strong><span>该条申请人为 {{ approvalFor(row.id)!.applicantId }}，请切换其他操作人。</span></td>
                </tr>
                <tr v-if="view === 'pending' && approvalFor(row.id) && rejectingKnowledgeId === row.id" class="inline-rejection-row">
                  <td colspan="10">
                    <div class="inline-rejection-form">
                      <label :for="`rejection-reason-${row.id}`">驳回原因</label>
                      <input :id="`rejection-reason-${row.id}`" v-model="rejectionReason" maxlength="1000" placeholder="请输入本条知识的驳回原因" @keyup.enter="confirmReject(approvalFor(row.id)!)" />
                      <button type="button" class="secondary-command" @click="cancelReject">取消</button>
                      <button type="button" class="reject-command" :disabled="approvalProcessingId === approvalFor(row.id)?.approvalId" @click="confirmReject(approvalFor(row.id)!)"><LoaderCircle v-if="approvalProcessingId === approvalFor(row.id)?.approvalId" class="spin" :size="15" /><X v-else :size="15" />确认驳回</button>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <footer class="kb-pagination"><span>第 {{ page }} / {{ totalPages }} 页</span><button title="上一页" :disabled="page <= 1" @click="changePage(page - 1)"><ChevronLeft :size="18" /></button><button title="下一页" :disabled="page >= totalPages" @click="changePage(page + 1)"><ChevronRight :size="18" /></button></footer>
      </section>
    </main>

    <ProblemCollectionView v-else-if="activeModule === 'problems'" v-model:operator-id="operatorId" />
    <EvaluationCenterView v-else v-model:operator-id="operatorId" />

    <div v-if="drawerOpen" class="kb-overlay" @click.self="drawerOpen = false">
      <aside class="kb-drawer kb-drawer-wide" aria-modal="true" role="dialog">
        <header><div><h2>{{ drawerTitle }}</h2><p v-if="visibleVersion">当前展示 V{{ visibleVersion.versionNo }}</p></div><button title="关闭" @click="drawerOpen = false"><X :size="20" /></button></header>
        <div v-if="detail?.latestApproval?.status === 2 && detail.latestApproval.rejectionReason" class="rejection-panel"><strong>上次驳回原因</strong><p>{{ detail.latestApproval.rejectionReason }}</p></div>
        <form @submit.prevent="saveKnowledge">
          <label>标题<input v-model="form.title" maxlength="256" required /></label>
          <div class="form-grid knowledge-classification-grid">
            <label><span>分类</span><select v-model="form.categoryId" :disabled="Boolean(editingId)" required><option v-for="item in categories" :key="item.id" :value="String(item.id)">{{ item.categoryName }}</option></select><small>{{ editingId ? '编辑版本时保留原分类' : '用于后台分类筛选与管理' }}</small></label>
            <label><span>意图编码</span><input v-model="form.intentCode" maxlength="64" placeholder="例如 refund_request" required /><small>用于知识召回路由，建议使用英文下划线格式</small></label>
          </div>
          <label>知识内容<textarea v-model="form.content" rows="6" required /></label>
          <KnowledgeChunkEditor v-model="chunkDrafts" :content="form.content" :title="form.title" />
          <label>标签<input v-model="form.tags" placeholder="多个标签用逗号分隔" /></label>
          <div class="form-grid"><label>生效时间<input v-model="form.effectiveAt" type="datetime-local" required /></label><label>失效时间<input v-model="form.expiredAt" type="datetime-local" /></label></div>
          <label>申请说明<textarea v-model="form.applicationReason" rows="3" maxlength="1000" placeholder="说明本次新增或修改原因" /></label>
          <footer>
            <button type="button" class="secondary-command" @click="drawerOpen = false">取消</button>
            <button v-if="editingId" type="button" class="secondary-command" :disabled="saving || savingDraft || approvalLocked" @click="saveKnowledgeDraft"><LoaderCircle v-if="savingDraft" class="spin" :size="17" /><Save v-else :size="17" />保存</button>
            <button class="primary-command" :disabled="saving || savingDraft || approvalLocked" type="submit"><LoaderCircle v-if="saving" class="spin" :size="17" /><Check v-else :size="17" />{{ approvalLocked ? '审批中' : '提交审批' }}</button>
          </footer>
        </form>
      </aside>
    </div>
  </div>
</template>
