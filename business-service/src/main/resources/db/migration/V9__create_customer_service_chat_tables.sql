-- Python 客服主链路的长期数据也交给 Flyway 管理，空数据库不再依赖 ORM 自动建表。
CREATE TABLE IF NOT EXISTS public.chat_conversation (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    title VARCHAR(120) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    channel VARCHAR(20) NOT NULL DEFAULT 'web',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_conversation_user_session UNIQUE (user_id, session_id)
);

CREATE TABLE IF NOT EXISTS public.chat_message (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL,
    role VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    intent VARCHAR(64),
    intent_confidence REAL,
    provider VARCHAR(40),
    latency_ms REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_message_request_id UNIQUE (request_id),
    CONSTRAINT fk_chat_message_conversation FOREIGN KEY (conversation_id)
        REFERENCES public.chat_conversation (id) ON DELETE CASCADE,
    CONSTRAINT ck_chat_message_role CHECK (role IN ('user', 'assistant', 'system'))
);

CREATE TABLE IF NOT EXISTS public.chat_feedback (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL,
    message_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    feedback_type VARCHAR(20) NOT NULL,
    rating INTEGER,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_feedback_user_message UNIQUE (user_id, message_id),
    CONSTRAINT fk_chat_feedback_conversation FOREIGN KEY (conversation_id)
        REFERENCES public.chat_conversation (id) ON DELETE CASCADE,
    CONSTRAINT fk_chat_feedback_message FOREIGN KEY (message_id)
        REFERENCES public.chat_message (id) ON DELETE CASCADE,
    CONSTRAINT ck_chat_feedback_type CHECK (feedback_type IN ('helpful', 'unhelpful')),
    CONSTRAINT ck_chat_feedback_rating CHECK (rating IS NULL OR rating BETWEEN 1 AND 5)
);

CREATE TABLE IF NOT EXISTS public.service_ticket (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    reason VARCHAR(120) NOT NULL,
    summary TEXT NOT NULL,
    context_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    assigned_agent_id VARCHAR(64),
    external_ticket_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_service_ticket_conversation FOREIGN KEY (conversation_id)
        REFERENCES public.chat_conversation (id) ON DELETE CASCADE,
    CONSTRAINT uk_service_ticket_external UNIQUE (external_ticket_id)
);

CREATE INDEX IF NOT EXISTS ix_conversation_user_updated
    ON public.chat_conversation (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_message_conversation_created
    ON public.chat_message (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS ix_feedback_type_created
    ON public.chat_feedback (feedback_type, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ticket_status_created
    ON public.service_ticket (status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ticket_conversation
    ON public.service_ticket (conversation_id);

CREATE TRIGGER trg_chat_conversation_updated_at
    BEFORE UPDATE ON public.chat_conversation
    FOR EACH ROW EXECUTE FUNCTION business.set_updated_at();
CREATE TRIGGER trg_chat_feedback_updated_at
    BEFORE UPDATE ON public.chat_feedback
    FOR EACH ROW EXECUTE FUNCTION business.set_updated_at();
CREATE TRIGGER trg_service_ticket_updated_at
    BEFORE UPDATE ON public.service_ticket
    FOR EACH ROW EXECUTE FUNCTION business.set_updated_at();

COMMENT ON TABLE public.chat_conversation IS 'Python智能客服会话';
COMMENT ON TABLE public.chat_message IS '用户与智能客服消息';
COMMENT ON TABLE public.chat_feedback IS '用户对具体AI回答的帮助度和评分反馈';
COMMENT ON TABLE public.service_ticket IS '申请人工后创建的客服工单';
