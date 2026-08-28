export interface ConversationSummary {
  id: string;
  session_id: string;
  title: string;
  status: string;
  channel: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  intent?: string | null;
  provider?: string | null;
  created_at: string;
}

async function request<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail || `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function listConversations(limit = 20, signal?: AbortSignal) {
  return request<ConversationSummary[]>(`/api/conversations?limit=${limit}`, signal);
}

export function listConversationMessages(conversationId: string, limit = 100, signal?: AbortSignal) {
  return request<ConversationMessage[]>(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages?limit=${limit}`,
    signal,
  );
}
