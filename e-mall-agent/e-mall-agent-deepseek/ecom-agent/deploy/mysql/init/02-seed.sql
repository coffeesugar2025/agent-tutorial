-- ============================================================================
-- 星图商城 · 电商智能体平台  演示数据（02-seed.sql）
--
-- 执行顺序：MySQL 官方镜像按文件名字典序执行 /docker-entrypoint-initdb.d
--           01-schema.sql（建库建表） → 02-seed.sql（灌演示数据）
--           仅在数据卷首次初始化时执行；重复执行会因主键冲突失败，重置见
--           deploy/scripts/reset.sh
--
-- 演示账号（三个账号密码统一为 `Passw0rd!`）
--   admin / Passw0rd!   角色 ADMIN,OPS   —— 知识库、可观测、评测、审批
--   alice / Passw0rd!   角色 USER        —— 主演示用户（有历史订单与待审批退款）
--   bob   / Passw0rd!   角色 USER        —— 对照用户（用于越权测试：bob 查不到 alice 的单）
--
-- 关于 password_hash：
--   使用 bcrypt(rounds=12, $2a$) 真实生成并本地校验通过，明文即 `Passw0rd!`。
--   $2a$ 前缀同时兼容 Python bcrypt 与 Spring Security BCryptPasswordEncoder / jBCrypt。
--   生产环境必须重置（见 docs/06-部署运维.md §9.4）。若改动密码，请在容器内生成：
--     python -c "import bcrypt;print(bcrypt.hashpw(b'新密码',bcrypt.gensalt(12)).decode())"
--   然后把输出写回 sys_user.password_hash，切勿使用网上随手复制的短串
--   （长度不是 60 的 bcrypt 串会让两端在校验时直接抛 Invalid salt）。
--
-- 数据规模：3 用户 / 2 类目 / 8 商品 / 6 订单（覆盖 6 种状态）/ 4 条物流 /
--           2 条退款 / 2 条审批 / 8 篇知识文档 / 7 个切片 / 2 条评测批次
-- ============================================================================

SET NAMES utf8mb4;
SET time_zone = '+08:00';
USE ecom_agent;

-- ---------------------------------------------------------------------------
-- 1. 用户 / 画像 / 长期记忆
-- ---------------------------------------------------------------------------
INSERT INTO sys_user (id, username, password_hash, display_name, email, roles, status) VALUES
(1, 'admin', '$2a$12$ckKBnWIBsvez9tOD17KQiOtnBywaYWif4KhiHhzozqkZc.8V2MvSC', '平台管理员', 'admin@xingtu.example.com', 'ADMIN,OPS', 1),
(2, 'alice', '$2a$12$ckKBnWIBsvez9tOD17KQiOtnBywaYWif4KhiHhzozqkZc.8V2MvSC', 'Alice', 'alice@xingtu.example.com', 'USER', 1),
(3, 'bob',   '$2a$12$ckKBnWIBsvez9tOD17KQiOtnBywaYWif4KhiHhzozqkZc.8V2MvSC', 'Bob',   'bob@xingtu.example.com',   'USER', 1);

INSERT INTO user_profile (user_id, nickname, phone, member_level, preferred_brands, budget_min, budget_max, sizes) VALUES
(1, '管理员', '13900000001', 'NORMAL', NULL, NULL, NULL, NULL),
(2, '爱丽丝', '13800001111', 'GOLD', '["Apple","星图"]', 2000.00, 6000.00, '{"shoe":"38","clothing":"M"}'),
(3, '鲍勃',   '13700002222', 'NORMAL', '["星图"]',       1000.00, 3000.00, NULL);

INSERT INTO user_memory (id, user_id, mem_type, content, importance, source_session, vector_id, created_at, expires_at) VALUES
(1, 2, 'SEMANTIC', '用户偏好轻薄且拍照好的手机，预算区间 2000-6000 元，倾向星图与 Apple 品牌。', 0.85, 1, NULL, '2026-11-21 10:06:00.000', NULL),
(2, 2, 'EPISODIC', '2026-11 购买星图 Buds Pro 2 后反馈右耳无声，已发起退款申请待人工审批。', 0.70, 2, NULL, '2026-11-23 09:10:02.000', '2027-05-23 09:10:02.000');

-- ---------------------------------------------------------------------------
-- 2. 类目 / 商品（8 个 SPU）
-- ---------------------------------------------------------------------------
INSERT INTO category (id, name, parent_id, sort) VALUES
(1, '手机数码', 0, 1),
(2, '电脑办公', 0, 2);

INSERT INTO product (id, sku, title, subtitle, brand, category_id, price, original_price, stock, status, rating, sales, image_url, attrs, description, search_text) VALUES
(1, 'PH-001', '星图 X9 Pro 5G 手机 12+256G 曜石黑', '5000 万像素三摄 · 6.78 英寸 2K 屏 · 5000mAh', '星图', 1, 4999.00, 5499.00, 120, 1, 4.8, 3200,
 'https://cdn.xingtu.example.com/p/PH-001.jpg',
 '{"color":"曜石黑","memory":"256G","ram":"12G","screen":"6.78英寸2K","camera":"5000万三摄","battery":"5000mAh","network":"5G","weight":"198g"}',
 '主打影像的旗舰直板机，主摄支持 OIS 光学防抖与夜景长曝。重量 198g，日常单手可握。',
 '星图 X9 Pro 手机 5G 拍照 影像 旗舰 5000万三摄 256G 曜石黑 游戏 长续航'),
(2, 'PH-002', '星图 X9 5G 手机 8+128G 冰川蓝', '4800 万双摄 · 6.55 英寸 OLED · 轻薄 179g', '星图', 1, 3299.00, 3599.00, 200, 1, 4.7, 5100,
 'https://cdn.xingtu.example.com/p/PH-002.jpg',
 '{"color":"冰川蓝","memory":"128G","ram":"8G","screen":"6.55英寸OLED","camera":"4800万双摄","battery":"4800mAh","network":"5G","weight":"179g"}',
 '均衡轻薄的中高端机型，日常拍照与社交场景够用，性价比高于 Pro 版本。',
 '星图 X9 手机 5G 拍照 轻薄 4800万双摄 128G 冰川蓝 中端 性价比'),
(3, 'PH-003', '星图 Air 轻旗舰 5G 手机 12+256G 云雾白', '6400 万主摄 · 6.7 英寸直屏 · 5500mAh', '星图', 1, 2199.00, 2499.00, 80, 1, 4.6, 8900,
 'https://cdn.xingtu.example.com/p/PH-003.jpg',
 '{"color":"云雾白","memory":"256G","ram":"12G","screen":"6.7英寸直屏","camera":"6400万主摄","battery":"5500mAh","network":"5G","weight":"205g"}',
 '大电池长续航机型，主摄解析力好，适合重度使用与外出差旅。',
 '星图 Air 轻旗舰 5G 手机 大电池 长续航 拍照 6400万 256G 云雾白 学生机'),
(4, 'NB-001', '星图 Book 14 轻薄本 i5/16G/512G 深空灰', '14 英寸 2.8K 120Hz · 1.32kg · 全金属', '星图', 2, 5499.00, 5999.00, 60, 1, 4.7, 1200,
 'https://cdn.xingtu.example.com/p/NB-001.jpg',
 '{"cpu":"i5-13500H","ram":"16G","ssd":"512G","screen":"14英寸2.8K120Hz","weight":"1.32kg","os":"Windows11"}',
 '面向办公与轻度创作的轻薄本，接口齐全，续航约 10 小时。',
 '星图 Book 14 笔记本电脑 轻薄本 办公 i5 16G 512G 2.8K 深空灰 学生本'),
(5, 'NB-002', '星图 Book Pro 16 创作本 i7/32G/1T 星空灰', '16 英寸 3.2K MiniLED · 独显 · 100W 快充', '星图', 2, 10999.00, 11999.00, 25, 1, 4.9, 320,
 'https://cdn.xingtu.example.com/p/NB-002.jpg',
 '{"cpu":"i7-13700H","ram":"32G","ssd":"1T","gpu":"RTX4060","screen":"16英寸3.2KMiniLED","weight":"1.98kg"}',
 '面向视频剪辑与三维渲染的创作本，色域覆盖 100% DCI-P3。',
 '星图 Book Pro 16 创作本 笔记本 剪辑 渲染 独显 i7 32G 1T MiniLED'),
(6, 'HP-001', '星图 Buds Pro 2 主动降噪真无线耳机 星空黑', '48dB 深度降噪 · LDAC · 单次 8 小时', '星图', 1, 1299.00, 1499.00, 300, 1, 4.8, 7600,
 'https://cdn.xingtu.example.com/p/HP-001.jpg',
 '{"color":"星空黑","anc":"48dB","battery":"8h+32h","bluetooth":"5.3","codec":"LDAC/AAC","weight":"4.8g"}',
 '旗舰降噪耳机，支持通透模式与双设备连接，佩戴 4.8g 无压迫感。',
 '星图 Buds Pro 2 蓝牙耳机 主动降噪 真无线 入耳式 LDAC 长续航 星空黑'),
(7, 'HP-002', '星图 Buds Air 3 半入耳蓝牙耳机 珍珠白', '半入耳舒适佩戴 · 通话降噪 · 单次 6 小时', '星图', 1, 599.00, 699.00, 500, 1, 4.6, 12000,
 'https://cdn.xingtu.example.com/p/HP-002.jpg',
 '{"color":"珍珠白","anc":"无","battery":"6h+24h","bluetooth":"5.3","codec":"AAC/SBC","weight":"3.9g"}',
 '半入耳设计久戴不胀，适合办公与通话场景，价格友好。',
 '星图 Buds Air 3 蓝牙耳机 半入耳 通话降噪 长续航 珍珠白 平价'),
(8, 'TB-001', '星图 Pad 11 平板 8+256G 星空灰', '11 英寸 2.5K 144Hz · 四扬声器 · 8000mAh', '星图', 2, 2799.00, 2999.00, 90, 1, 4.7, 2100,
 'https://cdn.xingtu.example.com/p/TB-001.jpg',
 '{"screen":"11英寸2.5K144Hz","memory":"256G","ram":"8G","battery":"8000mAh","speaker":"四扬声器","weight":"480g"}',
 '影音与网课向平板，支持手写笔与磁吸键盘（需另购）。',
 '星图 Pad 11 平板电脑 影音 网课 2.5K 144Hz 256G 星空灰 8000mAh');

-- ---------------------------------------------------------------------------
-- 3. 订单（6 单，覆盖 CREATED / PAID / SHIPPED / DELIVERED / FINISHED / REFUNDING）
--    CANCELLED / REFUNDED 由退款流程与取消接口在运行时产生，不在种子数据里造。
-- ---------------------------------------------------------------------------
INSERT INTO order_info (id, order_no, user_id, status, total_amount, pay_amount, receiver_name, receiver_phone, receiver_address, created_at, paid_at, shipped_at, finished_at) VALUES
(1, 'SO20261101000001', 2, 'CREATED',   4999.00,    0.00, '张三', '13800001111', '上海市浦东新区张江路 88 号 3 号楼 501', '2026-11-01 10:12:33.000', NULL, NULL, NULL),
(2, 'SO20261105000002', 2, 'PAID',      6098.00, 6098.00, '张三', '13800001111', '上海市浦东新区张江路 88 号 3 号楼 501', '2026-11-05 09:20:11.000', '2026-11-05 09:21:02.000', NULL, NULL),
(3, 'SO20261110000003', 2, 'SHIPPED',   1299.00, 1299.00, '张三', '13800001111', '上海市浦东新区张江路 88 号 3 号楼 501', '2026-11-10 20:05:44.000', '2026-11-10 20:06:10.000', '2026-11-11 14:30:00.000', NULL),
(4, 'SO20261115000004', 3, 'DELIVERED', 10999.00, 10999.00, '李四', '13700002222', '北京市海淀区中关村大街 1 号 A 座 1201',   '2026-11-15 11:02:07.000', '2026-11-15 11:03:33.000', '2026-11-16 08:15:00.000', NULL),
(5, 'SO20261118000005', 3, 'FINISHED',  599.00,   599.00, '李四', '13700002222', '北京市海淀区中关村大街 1 号 A 座 1201',   '2026-11-18 16:40:19.000', '2026-11-18 16:41:00.000', '2026-11-19 09:30:00.000', '2026-11-22 18:00:00.000'),
(6, 'SO20261120000006', 2, 'REFUNDING', 2799.00, 2799.00, '张三', '13800001111', '上海市浦东新区张江路 88 号 3 号楼 501', '2026-11-20 08:30:52.000', '2026-11-20 08:31:20.000', '2026-11-21 10:00:00.000', NULL);

INSERT INTO order_item (id, order_id, product_id, sku, title, price, quantity) VALUES
(1, 1, 1, 'PH-001', '星图 X9 Pro 5G 手机 12+256G 曜石黑', 4999.00, 1),
(2, 2, 4, 'NB-001', '星图 Book 14 轻薄本 i5/16G/512G 深空灰', 5499.00, 1),
(3, 2, 7, 'HP-002', '星图 Buds Air 3 半入耳蓝牙耳机 珍珠白', 599.00, 1),
(4, 3, 6, 'HP-001', '星图 Buds Pro 2 主动降噪真无线耳机 星空黑', 1299.00, 1),
(5, 4, 5, 'NB-002', '星图 Book Pro 16 创作本 i7/32G/1T 星空灰', 10999.00, 1),
(6, 5, 7, 'HP-002', '星图 Buds Air 3 半入耳蓝牙耳机 珍珠白', 599.00, 1),
(7, 6, 8, 'TB-001', '星图 Pad 11 平板 8+256G 星空灰', 2799.00, 1);

INSERT INTO logistics (id, order_id, order_no, company, tracking_no, status, latest_event, events, updated_at) VALUES
(1, 3, 'SO20261110000003', '顺丰速运', 'SF1234567890123', 'IN_TRANSIT', '快件已到达上海浦东转运中心',
 '[{"time":"2026-11-11 14:30:00","desc":"商家已发货，顺丰速运已揽收"},{"time":"2026-11-11 22:10:00","desc":"快件已到达上海虹桥分拣中心"},{"time":"2026-11-12 06:25:00","desc":"快件已到达上海浦东转运中心"}]',
 '2026-11-12 06:25:00.000'),
(2, 4, 'SO20261115000004', '京东物流', 'JD9876543210001', 'DELIVERED', '已签收，签收人：本人',
 '[{"time":"2026-11-16 08:15:00","desc":"商品出库完成"},{"time":"2026-11-16 15:40:00","desc":"快件已到达北京海淀配送站"},{"time":"2026-11-17 10:05:00","desc":"已签收，签收人：本人"}]',
 '2026-11-17 10:05:00.000'),
(3, 5, 'SO20261118000005', '中通快递', 'ZT5566778899001', 'DELIVERED', '已签收，签收人：前台代收',
 '[{"time":"2026-11-19 09:30:00","desc":"商家已发货，中通快递已揽收"},{"time":"2026-11-20 13:15:00","desc":"已签收，签收人：前台代收"}]',
 '2026-11-20 13:15:00.000'),
(4, 6, 'SO20261120000006', '顺丰速运', 'SF1234567890456', 'EXCEPTION', '客户申请退款，快件就地拦截中',
 '[{"time":"2026-11-21 10:00:00","desc":"商家已发货，顺丰速运已揽收"},{"time":"2026-11-22 09:45:00","desc":"客户申请退款，快件就地拦截中"}]',
 '2026-11-22 09:45:00.000');

-- ---------------------------------------------------------------------------
-- 4. 会话 / 消息 / 审批 / 退款
-- ---------------------------------------------------------------------------
INSERT INTO chat_session (id, user_id, title, agent_type, status, summary, created_at, updated_at, last_message_at) VALUES
(1, 2, '帮我挑一台拍照好的手机', 'SHOPPING', 'ACTIVE', NULL, '2026-11-21 09:58:00.000', '2026-11-21 10:05:00.000', '2026-11-21 10:05:00.000'),
(2, 2, '耳机右耳没声音，想退款', 'SERVICE', 'ACTIVE', NULL, '2026-11-23 09:09:30.000', '2026-11-23 09:10:05.000', '2026-11-23 09:10:05.000');

INSERT INTO chat_message (id, session_id, role, content, agent_type, tool_calls, citations, token_in, token_out, cost_cents, trace_id, created_at) VALUES
(1, 1, 'user', '预算 5000 以内，主要用来拍照，帮我推荐两台，最好能对比一下。', NULL, NULL, NULL, 0, 0, 0, 'tr-20261121-0001', '2026-11-21 10:00:12.000'),
(2, 1, 'assistant', '按 5000 元以内、影像优先筛选出两款：星图 X9 Pro（4999 元，5000 万三摄 + OIS）和星图 X9（3299 元，4800 万双摄 + 更轻薄）。前者长焦与夜景更好，后者便宜 1700 元且轻 19g。若你常在夜间或演唱会拍照，选 X9 Pro；若更看重手感与预算，选 X9。', 'SHOPPING',
 '[{"callId":"c1","name":"search_products","args":{"query":"拍照好的手机","topK":5,"maxPrice":5000},"ok":true,"summary":"命中 3 件"},{"callId":"c2","name":"compare_products","args":{"skus":["PH-001","PH-002"]},"ok":true,"summary":"对比 2 款，2 项关键差异"}]',
 '[{"docId":4,"chunkId":21,"title":"手机选购指南（2026版）","snippet":"夜景表现主要取决于主摄传感器尺寸与 OIS 光学防抖…","score":0.86}]',
 1200, 300, 2, 'tr-20261121-0001', '2026-11-21 10:05:00.000'),
(3, 2, 'user', '我上周买的耳机右耳没声音了，这种情况能退吗？', NULL, NULL, NULL, 0, 0, 0, 'tr-20261123-0001', '2026-11-23 09:09:40.000'),
(4, 2, 'assistant', '已核对：订单 SO20261110000003（星图 Buds Pro 2，1299 元）签收未超 7 天，且属于非人为损坏，符合 7 天无理由退货条件。我已为你提交退款申请，单笔 1299 元未超过自动放行阈值，但仍需客服在 24 小时内人工确认后才会执行退款，结果会通过站内消息通知你。', 'SERVICE',
 '[{"callId":"c3","name":"get_order","args":{"orderNo":"SO20261110000003"},"ok":true,"summary":"命中 1 单，状态 SHIPPED"},{"callId":"c4","name":"check_refund_eligibility","args":{"orderNo":"SO20261110000003"},"ok":true,"summary":"ELIGIBLE"},{"callId":"c5","name":"create_refund_request","args":{"orderNo":"SO20261110000003","reason":"耳机右耳无声","amount":1299},"ok":true,"summary":"已创建 RF20261123000001，待审批"}]',
 '[{"docId":1,"chunkId":3,"title":"7天无理由退货政策","snippet":"自签收次日起 7 个自然日内，商品完好可申请无理由退货…","score":0.91}]',
 1500, 420, 3, 'tr-20261123-0001', '2026-11-23 09:10:05.000');

INSERT INTO approval_task (id, session_id, message_id, user_id, action_type, title, detail, risk, status, decision_comment, decided_by, created_at, expires_at, decided_at) VALUES
(1, 2, 4, 2, 'CREATE_REFUND', '退款审批：SO20261110000003',
 '{"orderNo":"SO20261110000003","refundNo":"RF20261123000001","amount":1299.00,"currency":"CNY","reason":"耳机右耳无声","eligibility":"ELIGIBLE","policyRef":"7天无理由退货政策","items":[{"sku":"HP-001","title":"星图 Buds Pro 2 主动降噪真无线耳机 星空黑","quantity":1,"price":1299.00}],"customer":{"userId":2,"username":"alice","memberLevel":"GOLD"},"riskNote":"退款后需回收商品"}',
 'IRREVERSIBLE', 'PENDING', NULL, NULL, '2026-11-23 09:10:05.000', '2026-11-24 09:10:05.000', NULL),
(2, 2, 3, 2, 'CREATE_REFUND', '退款审批：SO20261120000006',
 '{"orderNo":"SO20261120000006","refundNo":"RF20261122000002","amount":2799.00,"currency":"CNY","reason":"平板屏幕有坏点","eligibility":"ELIGIBLE","policyRef":"7天无理由退货政策","items":[{"sku":"TB-001","title":"星图 Pad 11 平板 8+256G 星空灰","quantity":1,"price":2799.00}],"customer":{"userId":2,"username":"alice","memberLevel":"GOLD"}}',
 'IRREVERSIBLE', 'APPROVED', '同意退款，走原路返回，商品由顺丰上门取件', 1, '2026-11-22 09:41:00.000', '2026-11-23 09:41:00.000', '2026-11-22 09:50:00.000');

INSERT INTO refund_request (id, refund_no, order_id, user_id, reason, amount, status, idempotency_key, approval_id, created_at, updated_at) VALUES
(1, 'RF20261123000001', 3, 2, '耳机右耳无声，申请退货退款', 1299.00, 'PENDING_APPROVAL', 'refund:SO20261110000003:v1', 1, '2026-11-23 09:10:04.000', '2026-11-23 09:10:04.000'),
(2, 'RF20261122000002', 6, 2, '平板屏幕有坏点，申请退货退款', 2799.00, 'PROCESSING',       'refund:SO20261120000006:v1', 2, '2026-11-22 09:40:58.000', '2026-11-22 09:50:00.000');

-- ---------------------------------------------------------------------------
-- 5. 知识库（8 篇文档，覆盖 READY / INDEXING / FAILED）
-- ---------------------------------------------------------------------------
INSERT INTO knowledge_document (id, title, doc_type, source, visibility, status, version, chunk_count, checksum, created_at, updated_at, deleted_at) VALUES
(1, '7天无理由退货政策', 'POLICY', 'minio://ecom-files/knowledge/policy-return-7d.md', 'PUBLIC', 'READY', 1, 12,
 SHA2('xingtu-policy-return-7d-v1', 256), '2026-11-01 09:00:00.000', '2026-11-01 09:02:31.000', NULL),
(2, '物流时效与配送范围说明', 'POLICY', 'minio://ecom-files/knowledge/policy-logistics.md', 'PUBLIC', 'READY', 1, 6,
 SHA2('xingtu-policy-logistics-v1', 256), '2026-11-01 09:05:00.000', '2026-11-01 09:06:12.000', NULL),
(3, '星图商城会员权益手册', 'MANUAL', 'minio://ecom-files/knowledge/manual-member.md', 'PUBLIC', 'READY', 1, 9,
 SHA2('xingtu-manual-member-v2', 256), '2026-11-02 14:20:00.000', '2026-11-02 14:22:45.000', NULL),
(4, '手机选购指南（2026版）', 'PRODUCT_DOC', 'minio://ecom-files/knowledge/guide-phone-2026.md', 'PUBLIC', 'READY', 2, 15,
 SHA2('xingtu-guide-phone-2026-v2', 256), '2026-11-03 10:00:00.000', '2026-11-10 16:30:00.000', NULL),
(5, '退款与售后内部操作规范', 'MANUAL', 'minio://ecom-files/knowledge/internal-refund-sop.md', 'INTERNAL', 'READY', 1, 8,
 SHA2('xingtu-internal-refund-sop-v1', 256), '2026-11-04 11:00:00.000', '2026-11-04 11:01:38.000', NULL),
(6, '经营分析指标口径说明', 'MANUAL', 'minio://ecom-files/knowledge/ops-metric-definition.md', 'ADMIN', 'READY', 1, 5,
 SHA2('xingtu-ops-metric-v1', 256), '2026-11-05 15:00:00.000', '2026-11-05 15:00:52.000', NULL),
(7, '双11活动规则（草稿）', 'POLICY', 'minio://ecom-files/knowledge/policy-double11-draft.md', 'PUBLIC', 'INDEXING', 1, 0,
 SHA2('xingtu-policy-double11-draft-v1', 256), '2026-11-23 09:20:00.000', '2026-11-23 09:20:30.000', NULL),
(8, '旧版发票说明（已废弃）', 'POLICY', 'minio://ecom-files/knowledge/deprecated-invoice.md', 'PUBLIC', 'FAILED', 1, 0,
 SHA2('xingtu-deprecated-invoice-v1', 256), '2026-11-06 08:00:00.000', '2026-11-06 08:00:41.000', NULL);

INSERT INTO knowledge_chunk (id, document_id, chunk_no, content, parent_content, token_count, metadata, created_at) VALUES
(1, 1, 1, '第一条 适用范围：本政策适用于星图商城自营及平台入驻商家销售的实物商品（虚拟商品、定制类商品、鲜活易腐商品除外）。',
 '7天无理由退货政策 第一章 总则\n第一条 适用范围：本政策适用于星图商城自营及平台入驻商家销售的实物商品（虚拟商品、定制类商品、鲜活易腐商品除外）。\n第二条 起算时间：自签收次日起计算 7 个自然日，签收时间以物流系统回传为准。',
 42, '{"source":"policy-return-7d.md","section":"第一章 总则","lang":"zh"}', '2026-11-01 09:02:01.000'),
(2, 1, 2, '第二条 起算时间：自签收次日起计算 7 个自然日，签收时间以物流系统回传为准；无物流签收记录的，以订单完成时间为准。',
 '7天无理由退货政策 第一章 总则\n第一条 适用范围…\n第二条 起算时间：自签收次日起计算 7 个自然日，签收时间以物流系统回传为准；无物流签收记录的，以订单完成时间为准。',
 48, '{"source":"policy-return-7d.md","section":"第一章 总则","lang":"zh"}', '2026-11-01 09:02:03.000'),
(3, 1, 3, '第三条 商品完好标准：商品本体、配件、赠品、包装、说明书齐全，且不影响二次销售。已激活的手机、已拆封的耳机因卫生与激活限制，不支持无理由退货，但存在质量问题的除外。',
 '7天无理由退货政策 第二章 退货条件\n第三条 商品完好标准：商品本体、配件、赠品、包装、说明书齐全，且不影响二次销售。已激活的手机、已拆封的耳机因卫生与激活限制，不支持无理由退货，但存在质量问题的除外。',
 71, '{"source":"policy-return-7d.md","section":"第二章 退货条件","lang":"zh"}', '2026-11-01 09:02:08.000'),
(4, 1, 4, '第四条 退货运费：无理由退货的往返运费由消费者承担；因商品质量问题或商家发错货导致的退货，运费由商家承担。',
 '7天无理由退货政策 第三章 费用与退款\n第四条 退货运费：无理由退货的往返运费由消费者承担；因商品质量问题或商家发错货导致的退货，运费由商家承担。\n第五条 退款时效：商家签收退货后 48 小时内完成验货，验货通过后 1-3 个工作日原路退回。',
 55, '{"source":"policy-return-7d.md","section":"第三章 费用与退款","lang":"zh"}', '2026-11-01 09:02:14.000'),
(5, 2, 1, '配送时效：华东、华北、华南核心城市下单后 24 小时内发货，偏远地区 48 小时内发货；大促期间顺延 24-72 小时。',
 '物流时效与配送范围说明\n配送时效：华东、华北、华南核心城市下单后 24 小时内发货，偏远地区 48 小时内发货；大促期间顺延 24-72 小时。\n配送范围：港澳台及海外地区暂不支持直邮。',
 46, '{"source":"policy-logistics.md","section":"配送时效","lang":"zh"}', '2026-11-01 09:06:02.000'),
(6, 2, 2, '异常件处理：物流超过 72 小时无轨迹更新，可提交催单工单，客服将在 4 小时内联系承运商核实，并在 24 小时内反馈处理结果。',
 '物流时效与配送范围说明\n异常件处理：物流超过 72 小时无轨迹更新，可提交催单工单，客服将在 4 小时内联系承运商核实，并在 24 小时内反馈处理结果。',
 52, '{"source":"policy-logistics.md","section":"异常件处理","lang":"zh"}', '2026-11-01 09:06:09.000'),
(7, 5, 1, '内部规范：退款金额不超过 1000 元且用户等级为 GOLD 及以上可由一线客服直接审批；超过 1000 元需升级至售后主管；超过 5000 元需风控复核。所有审批动作必须留痕，禁止代客操作。',
 '退款与售后内部操作规范 第三章 审批权限\n内部规范：退款金额不超过 1000 元且用户等级为 GOLD 及以上可由一线客服直接审批；超过 1000 元需升级至售后主管；超过 5000 元需风控复核。所有审批动作必须留痕，禁止代客操作。',
 88, '{"source":"internal-refund-sop.md","section":"第三章 审批权限","lang":"zh","visibility":"INTERNAL"}', '2026-11-04 11:01:30.000');

INSERT INTO knowledge_job (id, document_id, job_type, status, progress, error, created_at, updated_at) VALUES
(1, 1, 'INDEX',   'SUCCESS', 100, NULL, '2026-11-01 09:00:10.000', '2026-11-01 09:02:31.000'),
(2, 7, 'REINDEX', 'RUNNING', 60,  NULL, '2026-11-23 09:20:10.000', '2026-11-23 09:20:30.000'),
(3, 8, 'INDEX',   'FAILED',  30,  '解析失败：文件编码非 UTF-8，请转码后重试', '2026-11-06 08:00:10.000', '2026-11-06 08:00:41.000');

-- ---------------------------------------------------------------------------
-- 6. 可观测性（1 条导购链路 + 1 条售后链路）
-- ---------------------------------------------------------------------------
INSERT INTO agent_trace (id, trace_id, session_id, user_id, agent_type, question, answer, status, total_latency_ms, total_cost_cents, step_count, created_at) VALUES
(1, 'tr-20261121-0001', 1, 2, 'SHOPPING', '预算 5000 以内，主要用来拍照，帮我推荐两台', '按 5000 元以内、影像优先筛选出两款…', 'SUCCESS', 1800, 2, 3, '2026-11-21 10:00:12.000'),
(2, 'tr-20261123-0001', 2, 2, 'SERVICE', '我上周买的耳机右耳没声音了，这种情况能退吗？', '已核对：订单 SO20261110000003 符合 7 天无理由退货…', 'SUCCESS', 2400, 3, 4, '2026-11-23 09:09:40.000');

INSERT INTO agent_span (id, trace_id, span_id, parent_span_id, name, span_type, seq, input, output, latency_ms, status, error, started_at) VALUES
(1, 'tr-20261123-0001', 'sp-0001', NULL,      'supervisor.route',            'AGENT',     1, '{"message":"我上周买的耳机右耳没声音了，这种情况能退吗？"}', '{"agentType":"SERVICE","reason":"售后意图"}', 260, 'OK', NULL, '2026-11-23 09:09:40.000'),
(2, 'tr-20261123-0001', 'sp-0002', 'sp-0001', 'service.tool.get_order',      'TOOL',      2, '{"orderNo":"SO20261110000003"}', '{"status":"SHIPPED","totalAmount":1299.0}', 85,  'OK', NULL, '2026-11-23 09:09:41.000'),
(3, 'tr-20261123-0001', 'sp-0003', 'sp-0001', 'service.rag.search',          'RETRIEVAL', 3, '{"query":"耳机拆封后能否无理由退货"}', '{"hits":3,"topScore":0.91}', 92,  'OK', NULL, '2026-11-23 09:09:42.000'),
(4, 'tr-20261123-0001', 'sp-0004', 'sp-0001', 'service.approval.create',     'GUARDRAIL', 4, '{"actionType":"CREATE_REFUND","amount":1299.0}', '{"approvalId":1,"status":"PENDING"}', 30, 'OK', NULL, '2026-11-23 09:09:43.000');

INSERT INTO llm_call (id, trace_id, span_id, provider, model, prompt_tokens, completion_tokens, cached_tokens, cost_cents, latency_ms, status, created_at) VALUES
(1, 'tr-20261121-0001', 'sp-0001', 'deepseek', 'deepseek-chat', 820,  180, 320, 1, 1200, 'OK', '2026-11-21 10:00:14.000'),
(2, 'tr-20261123-0001', 'sp-0001', 'deepseek', 'deepseek-chat', 1100, 240, 0,   2, 1500, 'OK', '2026-11-23 09:09:44.000'),
(3, 'tr-20261123-0001', 'sp-0003', 'dashscope', 'qwen-turbo',   420,  60,  0,   1, 260,  'OK', '2026-11-23 09:09:42.000');

INSERT INTO audit_log (id, user_id, action, target, detail, ip, created_at) VALUES
(1, 1, 'APPROVE_REFUND', 'approval:2', '{"decision":"APPROVE","refundNo":"RF20261122000002","comment":"同意退款，走原路返回"}', '10.0.8.21', '2026-11-22 09:50:00.000'),
(2, 1, 'KNOWLEDGE_UPLOAD', 'document:7', '{"fileName":"policy-double11-draft.md","docType":"POLICY","visibility":"PUBLIC"}', '10.0.8.21', '2026-11-23 09:20:00.000');

-- ---------------------------------------------------------------------------
-- 7. 评测
-- ---------------------------------------------------------------------------
INSERT INTO eval_run (id, suite, status, total, passed, pass_rate, pass_k, repeat_times, avg_cost_cents, avg_latency_ms, report, started_at, finished_at) VALUES
(1, 'shopping', 'SUCCESS', 20, 18, 0.9000, 0.7800, 3, 3, 2500,
 '{"judge":"rule+llm","failCases":["s-007","s-013"],"gate":{"passAt1":0.85,"passHatK":0.75},"passedGate":true}',
 '2026-11-22 21:00:00.000', '2026-11-22 21:06:12.000');

INSERT INTO eval_case_result (id, run_id, case_id, question, expected, actual, passed, score, attempts, detail) VALUES
(1, 1, 's-001', '预算 5000 以内拍照好的手机推荐', '必须包含 PH-001 或 PH-002，且给出价格', '推荐星图 X9 Pro（4999 元）与星图 X9（3299 元）', 1, 0.950, 3, '{"rule":"must_contain_sku","llmJudge":0.9}'),
(2, 1, 's-007', '对比 PH-001 与 NB-001 哪个更值得买', '应识别跨类目不可直接对比并澄清需求', '直接给出参数对比表并推荐 PH-001', 0, 0.400, 3, '{"rule":"must_clarify","llmJudge":0.4}');

-- ---------------------------------------------------------------------------
-- 8. 运行时支撑
-- ---------------------------------------------------------------------------
INSERT INTO idempotency_record (idem_key, scope, result, created_at, expires_at) VALUES
('refund:create:SO20261110000003:v1', 'refund',
 '{"refundNo":"RF20261123000001","approvalId":1,"status":"PENDING_APPROVAL"}',
 '2026-11-23 09:10:04.000', '2026-11-30 09:10:04.000');

INSERT INTO async_task (id, task_type, payload, status, retry, max_retry, error, created_at, updated_at) VALUES
(1, 'knowledge.index', '{"documentId":7,"jobId":2}', 'RUNNING', 0, 3, NULL, '2026-11-23 09:20:10.000', '2026-11-23 09:20:30.000'),
(2, 'eval.batch',      '{"runId":1,"suite":"shopping"}', 'SUCCESS', 0, 3, NULL, '2026-11-22 21:00:01.000', '2026-11-22 21:06:12.000');

INSERT INTO prompt_template (id, code, version, content, status, created_at) VALUES
(1, 'supervisor.system', 1,
 '你是星图商城的任务路由器。根据用户最新一句话判断意图，只输出一个 agentType：SHOPPING（商品导购、比价、对比）、SERVICE（订单、物流、售后、退款）、OPS（经营分析、报表）。判断不确定时优先 SUPERVISOR 追问澄清。禁止编造商品与订单信息。',
 'ACTIVE', '2026-11-01 08:00:00.000'),
(2, 'shopping.system', 1,
 '你是星图商城的导购顾问。回答必须基于 search_products / get_product_detail / compare_products 的真实返回，不得虚构价格、库存与参数。涉及对比时先给结论再列差异，最多推荐 3 款。引用知识库内容时保留 citations。',
 'ACTIVE', '2026-11-01 08:05:00.000');
