-- 知识库文档表（可选）：与后端 RAGPipeline.SEED_DOCS 的 8 条演示知识对齐
USE `ecom_agent`;

CREATE TABLE IF NOT EXISTS `rag_documents` (
  `id`         BIGINT       NOT NULL AUTO_INCREMENT,
  `source`     VARCHAR(64)  NOT NULL COMMENT '来源：售后政策/配送规则/优惠规则/支付与发票/商品知识',
  `category`   VARCHAR(32)  NOT NULL DEFAULT '',
  `content`    TEXT         NOT NULL,
  `enabled`    TINYINT(1)   NOT NULL DEFAULT 1,
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_rag_category` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `rag_documents` (`source`, `category`, `content`) VALUES
  ('售后政策',   'policy',     '七天无理由退货：签收后 7 天内，商品保持完好可申请退货。退款在仓库签收后 1-3 个工作日原路退回。'),
  ('售后政策',   'policy',     '质保规则：数码类商品整机保修 12 个月，人为损坏不在保修范围；家具类商品保修 36 个月。'),
  ('配送规则',   'logistics',  '配送时效：一线城市 1-2 天，其他地区 2-4 天。满 199 元包邮，未满收取 12 元运费。'),
  ('配送规则',   'logistics',  '发货时间：现货订单在付款后 24 小时内发出；预售商品以商品页标注时间为准。'),
  ('优惠规则',   'promotion',  '优惠券：新用户首单立减 30 元；会员订单满 500 减 50。同一订单只能使用一张优惠券。'),
  ('支付与发票', 'payment',    '发票：支持电子普通发票与增值税专用发票，订单完成后在订单详情页申请，1-2 个工作日开具。'),
  ('商品知识',   'product',    '无线降噪耳机 Pro：40 小时续航，主动降噪，支持蓝牙 5.3 与多点连接，适合通勤与办公。'),
  ('商品知识',   'product',    '人体工学椅：网布透气、腰托可调、扶手多向调节，建议久坐办公用户选择。');
