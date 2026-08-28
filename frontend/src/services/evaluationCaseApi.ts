export interface EvaluationCaseItem {
  id: number;
  caseCode: string;
  problemCode: string;
  knowledgeCode: string;
  knowledgeTitle: string;
  versionId: number;
  versionNo: number;
  questionText: string;
  expectedAnswer: string;
  expectedIntent: string;
  caseType: number;
  caseCategory: string;
  difficulty: number;
  sourceType: number;
  expectedMatch: boolean;
  status: number;
  generatedModel: string;
  createdBy: string;
  approvedBy?: string;
  createdAt: string;
  approvedAt?: string;
}

export interface EvaluationRunItem {
  id: number;
  runNo: string;
  problemCode: string;
  knowledgeCode: string;
  knowledgeTitle: string;
  versionId: number;
  versionNo: number;
  status: number;
  retryCount: number;
  totalCases: number;
  recallAt1?: number;
  recallAt3?: number;
  thresholdRecall?: number;
  positiveCases: number;
  hardNegativeCases: number;
  hardNegativeFalsePositiveRate?: number;
  errorCount?: number;
  averageLatencyMs?: number;
  p95LatencyMs?: number;
  distanceThreshold?: number;
  errorMessage?: string;
  startedAt?: string;
  finishedAt?: string;
  createdAt: string;
}

export interface EvaluationRunCaseResultItem {
  caseId: number;
  caseCode: string;
  questionText: string;
  caseCategory: string;
  difficulty: number;
  expectedMatch: boolean;
  passedAt1: boolean;
  passedAt3: boolean;
  passedThreshold: boolean;
  topDistance?: number;
  latencyMs?: number;
  errorMessage?: string;
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

export async function listEvaluationCases(
  query: URLSearchParams,
): Promise<PageResult<EvaluationCaseItem>> {
  const response = await fetch(`/business-api/admin/learning/evaluation-cases?${query}`);
  const payload = await response.json() as ApiEnvelope<PageResult<EvaluationCaseItem>>;
  if (!response.ok || !payload.success) {
    throw new Error(payload.message || `请求失败：${response.status}`);
  }
  return payload.data;
}

/** 读取由 Java 自动执行并持久化的知识发布验收批次。 */
export async function listEvaluationRuns(): Promise<PageResult<EvaluationRunItem>> {
  const response = await fetch('/business-api/admin/learning/evaluation-runs?page=1&size=50');
  const payload = await response.json() as ApiEnvelope<PageResult<EvaluationRunItem>>;
  if (!response.ok || !payload.success) {
    throw new Error(payload.message || `请求失败：${response.status}`);
  }
  return payload.data;
}

export async function listEvaluationRunResults(
  runId: number,
): Promise<EvaluationRunCaseResultItem[]> {
  const response = await fetch(`/business-api/admin/learning/evaluation-runs/${runId}/results`);
  const payload = await response.json() as ApiEnvelope<EvaluationRunCaseResultItem[]>;
  if (!response.ok || !payload.success) {
    throw new Error(payload.message || `请求失败：${response.status}`);
  }
  return payload.data;
}
