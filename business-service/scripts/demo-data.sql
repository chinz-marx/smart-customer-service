-- 仅供本地联调，生产环境不要执行此文件。
-- 执行前先让应用启动一次，Flyway 会自动创建 business schema 和表。
INSERT INTO business.business_order (
    order_no, user_id, status, logistics_text, expected_progress
) VALUES
    ('ORDER_123456', 'USER_10001', 'SHIPPED', '包裹已从上海分拨中心发出', '预计明天送达'),
    ('SHOP_778899', 'USER_10001', 'DELIVERED', '包裹已由本人签收', NULL),
    ('ORD_20260803_01', 'USER_10002', 'PROCESSING', '商家正在准备商品', '预计24小时内发货')
ON CONFLICT (order_no) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    status = EXCLUDED.status,
    logistics_text = EXCLUDED.logistics_text,
    expected_progress = EXCLUDED.expected_progress,
    deleted = FALSE;
