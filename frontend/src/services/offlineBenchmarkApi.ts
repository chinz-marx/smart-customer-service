export type BenchmarkType = 'retrieval' | 'intent';
export type BenchmarkStatus = 'queued' | 'running' | 'completed' | 'passed' | 'failed' | 'system_failed';

export interface BenchmarkDataset {
  id: string;
  name: string;
  description: string;
  evaluation_type: BenchmarkType;
  case_count: number;
  has_acceptance_thresholds: boolean;
}

export interface BenchmarkRun {
  run_id: string;
  dataset_id: string;
  dataset_name: string;
  evaluation_type: BenchmarkType;
  status: BenchmarkStatus;
  case_count: number;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  metrics: Record<string, unknown>;
  acceptance?: {
    passed?: boolean;
    checks?: Array<{ name: string; metric: string; operator: string; expected: number; actual: number; passed: boolean }>;
  };
  error_message?: string;
  stdout_summary?: string;
  json_report_name?: string;
  markdown_report_name?: string;
}

const API_ROOT = '/api/evaluation/benchmarks';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, options);
  const payload = await response.json().catch(() => ({})) as T & { detail?: string };
  if (!response.ok) throw new Error(payload.detail || `请求失败：${response.status}`);
  return payload;
}

export function listBenchmarkDatasets() {
  return request<BenchmarkDataset[]>('/datasets');
}

export function listBenchmarkRuns() {
  return request<BenchmarkRun[]>('/runs?limit=20');
}

export function startBenchmarkRun(datasetId: string) {
  return request<BenchmarkRun>('/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dataset_id: datasetId }),
  });
}

export function getBenchmarkRun(runId: string) {
  return request<BenchmarkRun>(`/runs/${encodeURIComponent(runId)}`);
}

export function benchmarkReportUrl(runId: string, format: 'json' | 'markdown') {
  return `${API_ROOT}/runs/${encodeURIComponent(runId)}/report?format=${format}`;
}
