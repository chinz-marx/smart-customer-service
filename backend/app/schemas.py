from pydantic import BaseModel, Field


class ChatHistoryItem(BaseModel):
    """前端传给后端的单条历史消息。"""

    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    """聊天接口请求体。"""

    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    """聊天接口响应体。"""

    answer: str
    session_id: str
    provider: str
    suggestions: list[str] = Field(default_factory=list)