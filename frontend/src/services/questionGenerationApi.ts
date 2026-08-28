export interface QuestionGenerationChunk {
  chunkNo: number;
  content: string;
  excludedQuestions?: string[];
}

export interface GeneratedQuestionChunk {
  chunkNo: number;
  questions: string[];
}

export interface KnowledgeContentChunk {
  chunkNo: number;
  content: string;
}

interface KnowledgeSplitResponse {
  chunks: Array<{
    chunk_no: number;
    content: string;
  }>;
}

interface QuestionGenerationResponse {
  provider: string;
  model: string;
  chunks: Array<{
    chunk_no: number;
    questions: string[];
  }>;
}

/**
 * 把原始正文交给Python统一切片，浏览器不再维护切片规则。
 */
export async function splitKnowledgeContent(content: string): Promise<KnowledgeContentChunk[]> {
  const response = await fetch('/api/knowledge/chunks/split', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail || '知识分片生成失败：' + response.status);
  }
  const payload = await response.json() as KnowledgeSplitResponse;
  return payload.chunks.map((chunk) => ({
    chunkNo: chunk.chunk_no,
    content: chunk.content,
  }));
}

/**
 * 调用Python的LLM标准问法生成接口。
 *
 * 该接口不写数据库，只返回候选问法；用户在页面确认并提交审批后才会持久化。
 */
export async function generateKnowledgeQuestions(
  title: string,
  questionCount: number,
  chunks: QuestionGenerationChunk[],
): Promise<GeneratedQuestionChunk[]> {
  const response = await fetch('/api/knowledge/questions/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title,
      question_count: questionCount,
      chunks: chunks.map((chunk) => ({
        chunk_no: chunk.chunkNo,
        content: chunk.content,
        excluded_questions: chunk.excludedQuestions ?? [],
      })),
    }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail || '标准问法生成失败：' + response.status);
  }
  const payload = await response.json() as QuestionGenerationResponse;
  return payload.chunks.map((chunk) => ({
    chunkNo: chunk.chunk_no,
    questions: chunk.questions,
  }));
}
