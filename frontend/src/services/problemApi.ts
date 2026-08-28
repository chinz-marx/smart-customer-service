export interface ProblemListItem {
  id: number;
  problemCode: string;
  representativeQuestion: string;
  problemSummary: string;
  intentCode?: string;
  confidence?: number;
  sourceType?: number;
  occurrenceCount: number;
  affectedUserCount: number;
  conversationCount: number;
  priority: number;
  status: number;
  standardAnswer?: string;
  answerProvider?: string;
  answerModel?: string;
  answerGeneratedBy?: string;
  answerGeneratedAt?: string;
  reviewedBy?: string;
  reviewedAt?: string;
  reviewComment?: string;
  rejectionReason?: string;
  reviewVersion: number;
  convertedKnowledgeId?: number;
  convertedVersionId?: number;
  convertedApprovalId?: number;
  convertedBy?: string;
  convertedAt?: string;
  firstSeenAt: string;
  lastSeenAt: string;
}

export interface ProblemSampleItem {
  id: number;
  rootQuestion: string;
  originalAnswer?: string;
  sourceType: number;
  confidence?: number;
  conversationId: string;
  occurredAt: string;
}

export interface ProblemReviewItem {
  id: number;
  actionType: number;
  statusBefore: number;
  statusAfter: number;
  answerSnapshot?: string;
  comment?: string;
  operatorId: string;
  createdAt: string;
  processedAt: string;
}

export interface ProblemDetail {
  problem: ProblemListItem;
  samples: ProblemSampleItem[];
  reviews: ProblemReviewItem[];
}

export interface LearningConversionPayload {
  categoryId: number;
  title: string;
  tags: string[];
  effectiveAt: string;
  expiredAt?: string;
  standardQuestions: string[];
  testCases: Array<{
    question: string;
    caseCategory: string;
    difficulty: number;
    sourceType: number;
    expectedMatch: boolean;
  }>;
  provider: string;
  model: string;
}

export interface LearningConversionResult {
  problemId: number;
  knowledgeId: number;
  versionId: number;
  approvalId: number;
  testCaseCount: number;
}

interface PageResult<T> {
  records: T[];
  total: number;
  page: number;
  size: number;
}

interface ApiEnvelope<T> {
  success: boolean;
  message: string;
  data: T;
}

const API_ROOT = '/business-api/admin/learning/problems';

async function request<T>(path = '', options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, options);
  const payload = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok || !payload.success) {
    throw new Error(payload.message || `请求失败：${response.status}`);
  }
  return payload.data;
}

function operatorHeaders(operatorId: string): HeadersInit {
  return { 'Content-Type': 'application/json', 'X-Operator-Id': operatorId };
}

export const problemApi = {
  list: (query: URLSearchParams) => request<PageResult<ProblemListItem>>(`?${query}`),
  detail: (id: number) => request<ProblemDetail>(`/${id}`),
  saveAnswer: (
    id: number,
    payload: { answer: string; provider: string; model: string },
    operatorId: string,
  ) => request<ProblemDetail>(`/${id}/standard-answer`, {
    method: 'PUT', headers: operatorHeaders(operatorId), body: JSON.stringify(payload),
  }),
  submitForReview: (id: number, operatorId: string) =>
    request<ProblemDetail>(`/${id}/submit-review`, {
      method: 'POST', headers: operatorHeaders(operatorId),
    }),
  approve: (id: number, comment: string, operatorId: string) =>
    request<ProblemDetail>(`/${id}/approve`, {
      method: 'POST', headers: operatorHeaders(operatorId), body: JSON.stringify({ comment }),
    }),
  reject: (id: number, rejectionReason: string, comment: string, operatorId: string) =>
    request<ProblemDetail>(`/${id}/reject`, {
      method: 'POST', headers: operatorHeaders(operatorId),
      body: JSON.stringify({ rejectionReason, comment }),
    }),
  ignore: (id: number, comment: string, operatorId: string) =>
    request<ProblemDetail>(`/${id}/ignore`, {
      method: 'POST', headers: operatorHeaders(operatorId), body: JSON.stringify({ comment }),
    }),
  convertToKnowledge: (id: number, payload: LearningConversionPayload, operatorId: string) =>
    request<LearningConversionResult>(`/${id}/convert-to-knowledge`, {
      method: 'POST', headers: operatorHeaders(operatorId), body: JSON.stringify(payload),
    }),
};
