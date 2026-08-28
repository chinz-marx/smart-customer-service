package com.smartcustomerservice.business.learning.domain;

/** 问题收集与审核使用的数字状态和审计动作。 */
public final class LearningProblemCodes {
    private LearningProblemCodes() {
    }

    public static final int STATUS_COLLECTING = 0;
    public static final int STATUS_PENDING_REVIEW = 1;
    public static final int STATUS_APPROVED = 2;
    public static final int STATUS_REJECTED = 3;
    public static final int STATUS_CONVERTED = 4;
    public static final int STATUS_IGNORED = 5;

    public static final int ACTION_GENERATED = 1;
    public static final int ACTION_EDITED = 2;
    public static final int ACTION_APPROVED = 3;
    public static final int ACTION_REJECTED = 4;
    public static final int ACTION_IGNORED = 5;
    public static final int ACTION_CONVERTED = 6;
    public static final int ACTION_SUBMITTED = 7;

    public static final int CASE_PENDING_APPROVAL = 0;
    public static final int CASE_PENDING_EVALUATION = 1;
    public static final int CASE_REJECTED = 2;
    public static final int CASE_ACTIVE = 3;

    public static final int EVALUATION_PENDING = 0;
    public static final int EVALUATION_PROCESSING = 1;
    public static final int EVALUATION_PASSED = 2;
    public static final int EVALUATION_FAILED = 3;
    public static final int EVALUATION_SYSTEM_FAILED = 4;
}
