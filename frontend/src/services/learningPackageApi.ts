import type { ProblemDetail } from './problemApi';

export interface GeneratedLearningPackage {
  title: string;
  content: string;
  tags: string[];
  standard_questions: string[];
  test_cases: Array<{
    question: string;
    expected_answer: string;
    expected_intent: string;
    case_category: 'conversational' | 'omitted' | 'typo' | 'inverted' | 'boundary' | 'hard_negative';
    difficulty: 'easy' | 'medium' | 'hard';
    source_type: 'real_user' | 'llm_generated';
    expected_match: boolean;
  }>;
  provider: string;
  model: string;
}

/** 已审核答案是唯一事实正文，模型只生成知识元数据和不同难度的问法。 */
export async function generateLearningPackage(
  detail: ProblemDetail,
  caseCount: number,
): Promise<GeneratedLearningPackage> {
  const response = await fetch('/api/learning/packages/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      problem_code: detail.problem.problemCode,
      summary: detail.problem.problemSummary,
      intent_code: detail.problem.intentCode,
      standard_answer: detail.problem.standardAnswer,
      sample_questions: detail.samples.map((item) => item.rootQuestion),
      case_count: caseCount,
    }),
  });
  const payload = await response.json() as GeneratedLearningPackage & { detail?: string };
  if (!response.ok) throw new Error(payload.detail || '知识草稿与测试集生成失败');
  return payload;
}
