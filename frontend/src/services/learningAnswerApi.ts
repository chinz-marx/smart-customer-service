import type { ProblemDetail } from './problemApi';

interface LearningAnswerResponse {
  answer: string;
  provider: string;
  model: string;
}

/** Python负责调用LLM，Java负责保存草稿和审核状态。 */
export async function generateLearningAnswer(detail: ProblemDetail): Promise<LearningAnswerResponse> {
  const response = await fetch('/api/learning/answers/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      problem_code: detail.problem.problemCode,
      summary: detail.problem.problemSummary,
      intent_code: detail.problem.intentCode || null,
      source_names: [...new Set(detail.samples.map((item) => sourceName(item.sourceType)))],
      sample_questions: detail.samples.map((item) => item.rootQuestion),
      previous_answers: detail.samples
        .map((item) => item.originalAnswer || '')
        .filter(Boolean)
        .slice(0, 5),
    }),
  });
  const payload = await response.json() as LearningAnswerResponse & { detail?: string };
  if (!response.ok) throw new Error(payload.detail || '标准回答生成失败');
  return payload;
}

function sourceName(value: number): string {
  return ({
    1: '没帮助', 2: '差评', 3: '申请人工', 4: '投诉', 5: 'Tool失败', 6: 'RAG无命中',
  } as Record<number, string>)[value] || '其他';
}
