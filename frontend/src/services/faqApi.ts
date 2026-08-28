export interface FaqQuestion {
  questionId: number;
  questionText: string;
}

export interface FaqQuestionPage {
  records: FaqQuestion[];
  total: number;
  page: number;
  size: number;
}

export interface FaqStreamDone {
  questionId: number;
  source: 'redis' | 'postgresql';
  sessionId: string;
  conversationId: string;
  userMessageId: string;
  assistantMessageId: string;
  createdAt: string;
}

interface ToolResponse<T> {
  success: boolean;
  code: string;
  message: string;
  data: T;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/business-api/customer/faqs${path}`, options);
  const payload = (await response.json().catch(() => null)) as ToolResponse<T> | null;
  if (!response.ok || !payload?.success) {
    throw new Error(payload?.message || `请求失败：${response.status}`);
  }
  return payload.data;
}

export function listFaqQuestions(page = 1, size = 5) {
  return request<FaqQuestionPage>(`?page=${page}&size=${size}`);
}

export async function startFaqAnswerStream(
  questionId: number,
  context: { sessionId: string | null; conversationId: string | null },
  signal?: AbortSignal,
) {
  const response = await fetch(`/business-api/customer/faqs/${questionId}/answer/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(context),
    signal,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { message?: string } | null;
    throw new Error(payload?.message || `请求失败：${response.status}`);
  }
  return response;
}
