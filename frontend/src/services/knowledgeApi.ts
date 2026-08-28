export interface Category {
  id: number;
  categoryCode: string;
  categoryName: string;
}

export interface KnowledgeListItem {
  id: number;
  knowledgeCode: string;
  categoryId: number;
  categoryName: string;
  status: number;
  versionId: number;
  versionNo: number;
  versionStatus: number;
  title: string;
  intentCode?: string;
  createdBy: string;
  updatedBy: string;
  approverId?: string;
  rejectionReason?: string;
  createdAt: string;
  publishedAt?: string;
}

export interface KnowledgeVersion {
  id: number;
  versionNo: number;
  title: string;
  content: string;
  tags: string[];
  intentCode?: string;
  versionStatus: number;
  effectiveAt: string;
  expiredAt?: string;
  publishedAt?: string;
}

export interface Approval {
  id: number;
  status: number;
  actionType: number;
  applicantId: string;
  approverId?: string;
  rejectionReason?: string;
  applicationReason?: string;
}

export interface KnowledgeChunkItem {
  id?: number;
  chunkNo?: number;
  content: string;
  questions: string[];
}
export interface KnowledgeDetail {
  knowledge: {
    id: number;
    categoryId: number;
    status: number;
    pendingVersionId?: number;
  };
  categoryName: string;
  currentVersion?: KnowledgeVersion;
  pendingVersion?: KnowledgeVersion;
  latestApproval?: Approval;
  chunks: KnowledgeChunkItem[];
}

export interface ApprovalListItem {
  approvalId: number;
  approvalNo: string;
  knowledgeId: number;
  versionId: number;
  actionType: number;
  title: string;
  categoryName: string;
  versionNo: number;
  applicantId: string;
  applicationReason?: string;
  submittedAt: string;
}

export interface PageResult<T> {
  records: T[];
  total: number;
  page: number;
  size: number;
}

export interface KnowledgeFormPayload {
  title: string;
  categoryId: number;
  content: string;
  tags: string[];
  intentCode?: string;
  effectiveAt: string;
  expiredAt?: string;
  applicationReason?: string;
  chunks: Array<{ content: string; questions: string[] }>;
}

interface ApiEnvelope<T> {
  success: boolean;
  code: string;
  message: string;
  data: T;
}

const API_ROOT = '/business-api/admin/knowledge';

async function request<T>(path = '', options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, options);
  const payload = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok || !payload.success) {
    throw new Error(payload.message || `请求失败：${response.status}`);
  }
  return payload.data;
}

function operatorHeaders(operatorId: string): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-Operator-Id': operatorId,
  };
}

export const knowledgeApi = {
  categories: () => request<Category[]>('/categories'),
  list: (query: URLSearchParams) => request<PageResult<KnowledgeListItem>>(`?${query}`),
  detail: (id: number) => request<KnowledgeDetail>(`/${id}`),
  create: (payload: KnowledgeFormPayload, operatorId: string) =>
    request<KnowledgeDetail>('', {
      method: 'POST', headers: operatorHeaders(operatorId), body: JSON.stringify(payload),
    }),
  update: (id: number, payload: KnowledgeFormPayload, operatorId: string) =>
    request<KnowledgeDetail>(`/${id}`, {
      method: 'PUT', headers: operatorHeaders(operatorId), body: JSON.stringify(payload),
    }),
  saveDraft: (id: number, payload: KnowledgeFormPayload, operatorId: string) =>
    request<KnowledgeDetail>(`/${id}/draft`, {
      method: 'PUT', headers: operatorHeaders(operatorId), body: JSON.stringify(payload),
    }),
  disable: (id: number, operatorId: string) =>
    request<KnowledgeDetail>(`/${id}`, {
      method: 'DELETE', headers: operatorHeaders(operatorId),
    }),
  approvals: (page = 1, size = 50) =>
    request<PageResult<ApprovalListItem>>(`/approvals?page=${page}&size=${size}`),
  approve: (id: number, operatorId: string, comment = '') =>
    request<Approval>(`/approvals/${id}/approve`, {
      method: 'POST', headers: operatorHeaders(operatorId), body: JSON.stringify({ comment }),
    }),
  reject: (id: number, operatorId: string, rejectionReason: string) =>
    request<Approval>(`/approvals/${id}/reject`, {
      method: 'POST', headers: operatorHeaders(operatorId),
      body: JSON.stringify({ rejectionReason }),
    }),
};
