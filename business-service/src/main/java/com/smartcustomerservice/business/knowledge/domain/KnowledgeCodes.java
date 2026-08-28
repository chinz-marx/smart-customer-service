package com.smartcustomerservice.business.knowledge.domain;

/** 数据库保存数字状态；代码使用有名字的常量，避免散落难懂的 0、1、2。 */
public final class KnowledgeCodes {
    private KnowledgeCodes() {
    }

    public static final int KNOWLEDGE_INACTIVE = 0;
    public static final int KNOWLEDGE_ACTIVE = 1;
    public static final int VERSION_DRAFT = 0;
    public static final int VERSION_PENDING = 1;
    public static final int VERSION_PUBLISHED = 2;
    public static final int VERSION_REJECTED = 3;
    public static final int VERSION_ARCHIVED = 4;
    public static final int VERSION_WAITING_EVALUATION = 5;
    public static final int ACTION_CREATE = 1;
    public static final int ACTION_UPDATE = 2;
    public static final int ACTION_DISABLE = 3;
    public static final int APPROVAL_PENDING = 0;
    public static final int APPROVAL_APPROVED = 1;
    public static final int APPROVAL_REJECTED = 2;
    public static final int APPROVAL_CANCELED = 3;
    public static final int CHUNK_PENDING = 0;
    public static final int CHUNK_SUCCESS = 1;
    public static final int EVENT_UPSERT = 1;
    public static final int EVENT_DELETE = 2;
    public static final int OUTBOX_PENDING = 0;
    public static final int OUTBOX_PROCESSING = 1;
    public static final int OUTBOX_SUCCESS = 2;
    public static final int OUTBOX_FAILED = 3;
}
