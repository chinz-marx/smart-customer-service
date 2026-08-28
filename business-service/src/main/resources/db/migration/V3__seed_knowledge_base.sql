-- 将原 Python knowledge.yaml 中的模拟知识迁入 PostgreSQL。
-- 这些数据视为迁移前已经审核通过的初始版本，并通过 Outbox 等待写入 Redis Search。

INSERT INTO business.kb_category (
    category_code, category_name, sort_order, status, created_by, updated_by
)
VALUES
    ('faq', 'FAQ', 10, 1, 'system-migration', 'system-migration'),
    ('activity_rules', '活动规则', 20, 1, 'system-migration', 'system-migration'),
    ('member_benefits', '会员权益', 30, 1, 'system-migration', 'system-migration'),
    ('refund_rules', '退款规则', 40, 1, 'system-migration', 'system-migration'),
    ('order_guide', '订单说明', 50, 1, 'system-migration', 'system-migration');

WITH source_data(knowledge_code, category_code, title, content, intent_code) AS (
    VALUES
        ('faq_service_hours', 'faq', '人工客服的服务时间是什么时候',
         '人工客服服务时间为每天9:00至21:00，非服务时段提交的问题会进入待处理队列。', 'human_handoff'),
        ('faq_invoice', 'faq', '购买商品后怎么申请电子发票',
         '订单完成后可在订单详情中选择“申请发票”，填写抬头与邮箱后提交。', 'order_query'),
        ('faq_account_security', 'faq', '账号出现异常登录应该怎么办',
         '请立即修改密码并停止提供验证码、身份证号或银行卡信息，同时联系人工客服核验账号。', 'human_handoff'),
        ('faq_points_expire', 'faq', '积分会不会过期',
         '积分有效期以积分明细页显示为准；临近过期的积分会在页面中单独提示。', 'points_query'),
        ('faq_coupon_location', 'faq', '已领取的优惠券在哪里查看',
         '可在“我的-卡券”中查看已领取、可使用和已失效的优惠券。', 'benefits_query'),

        ('activity_new_user', 'activity_rules', '新用户活动需要满足什么条件',
         '新用户活动仅限活动开始后首次注册且完成实名认证的用户参加，具体以活动页面展示条件为准。', 'activity_rules'),
        ('activity_end_time', 'activity_rules', '活动什么时候结束',
         '活动结束时间以活动详情页显示的北京时间为准；达到名额上限时可能提前结束。', 'activity_rules'),
        ('activity_invite', 'activity_rules', '邀请好友后奖励怎么发',
         '好友通过专属邀请入口完成注册并满足活动条件后，奖励通常在3个工作日内发放。', 'activity_rules'),
        ('activity_quota', 'activity_rules', '活动有没有参与名额限制',
         '部分活动设有总名额或每日名额，是否还有名额以活动页面实时状态为准。', 'activity_rules'),
        ('activity_repeat', 'activity_rules', '同一个活动能不能重复参加',
         '除活动规则明确允许外，同一用户通常只能获得一次活动奖励，请以活动详情页为准。', 'activity_rules'),

        ('benefit_member_levels', 'member_benefits', '会员等级是怎么划分的',
         '会员等级根据近12个月的成长值计算，当前等级和升级进度可在会员中心查看。', 'benefits_query'),
        ('benefit_birthday', 'member_benefits', '生日会员有什么权益',
         '完成生日信息登记的会员可在生日月查看专属权益，具体内容以会员中心当月展示为准。', 'benefits_query'),
        ('benefit_shipping', 'member_benefits', '会员是否可以免运费',
         '部分会员等级享有指定商品或指定次数的免运费权益，使用范围以结算页提示为准。', 'benefits_query'),
        ('benefit_coupon', 'member_benefits', '会员优惠券怎么领取',
         '可在会员中心的“可领权益”中领取优惠券，领取后请在有效期和适用范围内使用。', 'benefits_query'),
        ('benefit_expire', 'member_benefits', '会员权益到期后还能使用吗',
         '已过有效期的会员权益不能继续使用；权益有效期可在会员中心对应权益详情中查看。', 'benefits_query'),

        ('refund_conditions', 'refund_rules', '什么情况下可以申请退款',
         '未发货订单通常可直接申请退款；已发货订单需按售后页面选择退货退款并满足商品售后条件。', 'refund_request'),
        ('refund_arrival', 'refund_rules', '退款审核通过后多久到账',
         '退款审核通过后会原路退回，到账时间通常为1至7个工作日，具体取决于支付机构。', 'refund_request'),
        ('refund_original_route', 'refund_rules', '退款会退到哪里',
         '退款默认原路退回至原支付账户，无法自行改到其他银行卡或支付账户。', 'refund_request'),
        ('refund_coupon', 'refund_rules', '退款后优惠券会退回来吗',
         '未过期且符合返还规则的优惠券会自动退回账户；已过期或特殊活动券可能无法返还。', 'refund_request'),
        ('refund_promotion', 'refund_rules', '满减订单退款金额怎么计算',
         '满减订单退款会按各商品实际支付金额分摊计算，最终金额以售后申请页面展示为准。', 'refund_request'),

        ('order_status', 'order_guide', '在哪里查看订单状态',
         '可在“我的订单”中打开对应订单查看付款、发货、运输和签收状态。', 'order_query'),
        ('order_address', 'order_guide', '下单后还能修改收货地址吗',
         '订单未进入发货流程时可尝试修改地址；已发货订单需要联系承运方或人工客服确认。', 'order_query'),
        ('order_cancel', 'order_guide', '已付款订单怎么取消',
         '尚未发货的订单可在订单详情中申请取消；已发货订单需要按售后流程处理。', 'order_query'),
        ('order_shipped_cancel', 'order_guide', '商品已经发货还能取消订单吗',
         '已发货订单通常不能直接取消，可在签收前联系承运方，或签收后按退货规则申请售后。', 'order_query'),
        ('order_logistics_delay', 'order_guide', '物流信息长时间不更新怎么办',
         '物流超过48小时未更新时，可先通过订单详情联系承运方；仍无进展可提交人工客服核查。', 'order_query')
)
INSERT INTO business.kb_knowledge (
    knowledge_code, category_id, status, created_by, updated_by
)
SELECT
    source_data.knowledge_code,
    category.id,
    1,
    'system-migration',
    'system-migration'
FROM source_data
JOIN business.kb_category category
    ON category.category_code = source_data.category_code;

WITH source_data(knowledge_code, category_code, title, content, intent_code) AS (
    VALUES
        ('faq_service_hours', 'faq', '人工客服的服务时间是什么时候', '人工客服服务时间为每天9:00至21:00，非服务时段提交的问题会进入待处理队列。', 'human_handoff'),
        ('faq_invoice', 'faq', '购买商品后怎么申请电子发票', '订单完成后可在订单详情中选择“申请发票”，填写抬头与邮箱后提交。', 'order_query'),
        ('faq_account_security', 'faq', '账号出现异常登录应该怎么办', '请立即修改密码并停止提供验证码、身份证号或银行卡信息，同时联系人工客服核验账号。', 'human_handoff'),
        ('faq_points_expire', 'faq', '积分会不会过期', '积分有效期以积分明细页显示为准；临近过期的积分会在页面中单独提示。', 'points_query'),
        ('faq_coupon_location', 'faq', '已领取的优惠券在哪里查看', '可在“我的-卡券”中查看已领取、可使用和已失效的优惠券。', 'benefits_query'),
        ('activity_new_user', 'activity_rules', '新用户活动需要满足什么条件', '新用户活动仅限活动开始后首次注册且完成实名认证的用户参加，具体以活动页面展示条件为准。', 'activity_rules'),
        ('activity_end_time', 'activity_rules', '活动什么时候结束', '活动结束时间以活动详情页显示的北京时间为准；达到名额上限时可能提前结束。', 'activity_rules'),
        ('activity_invite', 'activity_rules', '邀请好友后奖励怎么发', '好友通过专属邀请入口完成注册并满足活动条件后，奖励通常在3个工作日内发放。', 'activity_rules'),
        ('activity_quota', 'activity_rules', '活动有没有参与名额限制', '部分活动设有总名额或每日名额，是否还有名额以活动页面实时状态为准。', 'activity_rules'),
        ('activity_repeat', 'activity_rules', '同一个活动能不能重复参加', '除活动规则明确允许外，同一用户通常只能获得一次活动奖励，请以活动详情页为准。', 'activity_rules'),
        ('benefit_member_levels', 'member_benefits', '会员等级是怎么划分的', '会员等级根据近12个月的成长值计算，当前等级和升级进度可在会员中心查看。', 'benefits_query'),
        ('benefit_birthday', 'member_benefits', '生日会员有什么权益', '完成生日信息登记的会员可在生日月查看专属权益，具体内容以会员中心当月展示为准。', 'benefits_query'),
        ('benefit_shipping', 'member_benefits', '会员是否可以免运费', '部分会员等级享有指定商品或指定次数的免运费权益，使用范围以结算页提示为准。', 'benefits_query'),
        ('benefit_coupon', 'member_benefits', '会员优惠券怎么领取', '可在会员中心的“可领权益”中领取优惠券，领取后请在有效期和适用范围内使用。', 'benefits_query'),
        ('benefit_expire', 'member_benefits', '会员权益到期后还能使用吗', '已过有效期的会员权益不能继续使用；权益有效期可在会员中心对应权益详情中查看。', 'benefits_query'),
        ('refund_conditions', 'refund_rules', '什么情况下可以申请退款', '未发货订单通常可直接申请退款；已发货订单需按售后页面选择退货退款并满足商品售后条件。', 'refund_request'),
        ('refund_arrival', 'refund_rules', '退款审核通过后多久到账', '退款审核通过后会原路退回，到账时间通常为1至7个工作日，具体取决于支付机构。', 'refund_request'),
        ('refund_original_route', 'refund_rules', '退款会退到哪里', '退款默认原路退回至原支付账户，无法自行改到其他银行卡或支付账户。', 'refund_request'),
        ('refund_coupon', 'refund_rules', '退款后优惠券会退回来吗', '未过期且符合返还规则的优惠券会自动退回账户；已过期或特殊活动券可能无法返还。', 'refund_request'),
        ('refund_promotion', 'refund_rules', '满减订单退款金额怎么计算', '满减订单退款会按各商品实际支付金额分摊计算，最终金额以售后申请页面展示为准。', 'refund_request'),
        ('order_status', 'order_guide', '在哪里查看订单状态', '可在“我的订单”中打开对应订单查看付款、发货、运输和签收状态。', 'order_query'),
        ('order_address', 'order_guide', '下单后还能修改收货地址吗', '订单未进入发货流程时可尝试修改地址；已发货订单需要联系承运方或人工客服确认。', 'order_query'),
        ('order_cancel', 'order_guide', '已付款订单怎么取消', '尚未发货的订单可在订单详情中申请取消；已发货订单需要按售后流程处理。', 'order_query'),
        ('order_shipped_cancel', 'order_guide', '商品已经发货还能取消订单吗', '已发货订单通常不能直接取消，可在签收前联系承运方，或签收后按退货规则申请售后。', 'order_query'),
        ('order_logistics_delay', 'order_guide', '物流信息长时间不更新怎么办', '物流超过48小时未更新时，可先通过订单详情联系承运方；仍无进展可提交人工客服核查。', 'order_query')
)
INSERT INTO business.kb_knowledge_version (
    knowledge_id, version_no, title, content, tags, intent_code, version_status,
    effective_at, published_at, created_by, updated_by
)
SELECT
    knowledge.id,
    1,
    source_data.title,
    source_data.content,
    ARRAY[category.category_name]::VARCHAR(64)[],
    source_data.intent_code,
    2,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP,
    'system-migration',
    'system-migration'
FROM source_data
JOIN business.kb_knowledge knowledge
    ON knowledge.knowledge_code = source_data.knowledge_code
JOIN business.kb_category category
    ON category.id = knowledge.category_id;

UPDATE business.kb_knowledge knowledge
SET current_version_id = version.id
FROM business.kb_knowledge_version version
WHERE version.knowledge_id = knowledge.id
  AND version.version_no = 1;

INSERT INTO business.kb_approval (
    approval_no, knowledge_id, version_id, action_type, status,
    applicant_id, approver_id, application_reason, approval_comment,
    submitted_at, finished_at
)
SELECT
    'MIGRATION-' || knowledge.knowledge_code,
    knowledge.id,
    version.id,
    1,
    1,
    'system-migration',
    'system-migration',
    '从Python模拟知识库迁移',
    '系统初始化数据',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM business.kb_knowledge knowledge
JOIN business.kb_knowledge_version version
    ON version.id = knowledge.current_version_id;

INSERT INTO business.kb_outbox_event (
    event_id, knowledge_id, version_id, event_type, payload
)
SELECT
    'MIGRATION-' || knowledge.knowledge_code,
    knowledge.id,
    version.id,
    1,
    jsonb_build_object('source', 'flyway-migration', 'knowledgeCode', knowledge.knowledge_code)
FROM business.kb_knowledge knowledge
JOIN business.kb_knowledge_version version
    ON version.id = knowledge.current_version_id;
