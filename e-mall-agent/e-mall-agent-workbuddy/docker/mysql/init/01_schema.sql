-- 电商智能体业务库初始化（仅在 MySQL 数据卷首次创建时执行）
-- 数据与 Python 后端 InMemoryRepository 的演示种子保持一致
CREATE DATABASE IF NOT EXISTS `ecom_agent`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `ecom_agent`;

-- ---------------- 用户 ----------------
CREATE TABLE IF NOT EXISTS `users` (
  `id`         VARCHAR(32)  NOT NULL COMMENT '用户编号 U001/S001/A001',
  `name`       VARCHAR(64)  NOT NULL DEFAULT '' COMMENT '演示账号姓名',
  `role`       VARCHAR(16)  NOT NULL DEFAULT 'guest' COMMENT 'customer/service/admin',
  `password`   VARCHAR(128) NOT NULL DEFAULT '' COMMENT 'demo 明文口令，与后端演示数据一致',
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `users` (`id`, `name`, `role`, `password`) VALUES
  ('U001', '张三',   'customer', '123456'),
  ('U002', '李四',   'customer', '123456'),
  ('S001', '王客服', 'service',  '123456'),
  ('A001', '管理员', 'admin',    '123456')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`), `role`=VALUES(`role`);

-- ---------------- 商品 ----------------
CREATE TABLE IF NOT EXISTS `products` (
  `id`          VARCHAR(32)   NOT NULL COMMENT '商品编号 P001-P008',
  `name`        VARCHAR(128)  NOT NULL,
  `category`    VARCHAR(32)   NOT NULL DEFAULT '',
  `price`       DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  `stock`       INT           NOT NULL DEFAULT 0,
  `tags`        JSON          NULL COMMENT '标签数组，如 ["音频","热销"]',
  `description` TEXT          NULL,
  `created_at`  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `products` (`id`, `name`, `category`, `price`, `stock`, `tags`, `description`) VALUES
  ('P001', '无线降噪耳机 Pro',   '数码',  899.00, 12,  JSON_ARRAY('音频','热销','降噪'),   '40小时续航，主动降噪，适合通勤与办公。'),
  ('P002', '便携咖啡机',         '家居',  359.00, 5,   JSON_ARRAY('咖啡','便携'),          '手压萃取，随行制作意式浓缩。'),
  ('P003', '人体工学椅',         '家具', 1299.00, 3,   JSON_ARRAY('办公','护腰'),          '网布透气，腰托可调，久坐友好。'),
  ('P004', '智能手表 S2',        '数码', 1099.00, 20,  JSON_ARRAY('穿戴','健康'),          '心率血氧监测，14天续航。'),
  ('P005', '移动电源 20000mAh',  '数码',  199.00, 50,  JSON_ARRAY('充电','出行'),          '22.5W 快充，可带上飞机。'),
  ('P006', '机械键盘 87键',      '数码',  459.00, 8,   JSON_ARRAY('键盘','办公'),          '茶轴手感，紧凑布局，支持热插拔。'),
  ('P007', '空气循环扇',         '家电',  299.00, 0,   JSON_ARRAY('风扇','静音'),          '直流变频，低噪循环送风。'),
  ('P008', '保温杯 500ml',       '家居',  129.00, 100, JSON_ARRAY('水杯','保温'),          '316不锈钢，12小时保温。')
ON DUPLICATE KEY UPDATE `name`=VALUES(`name`), `price`=VALUES(`price`), `stock`=VALUES(`stock`);

-- ---------------- 订单 ----------------
-- created_at 用 VARCHAR(64) 存 ISO8601 UTC 字符串，与后端适配器写入格式一致
CREATE TABLE IF NOT EXISTS `orders` (
  `id`          VARCHAR(32)   NOT NULL COMMENT '订单编号 O1001-O1003',
  `customer_id` VARCHAR(32)   NOT NULL,
  `total`       DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  `status`      VARCHAR(32)   NOT NULL DEFAULT 'created',
  `created_at`  VARCHAR(64)   NOT NULL DEFAULT '' COMMENT 'ISO8601 UTC，如 2026-11-18T09:12:00+00:00',
  `address`     VARCHAR(255)  NOT NULL DEFAULT '',
  PRIMARY KEY (`id`),
  KEY `idx_orders_customer` (`customer_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `orders` (`id`, `customer_id`, `total`, `status`, `created_at`, `address`) VALUES
  ('O1001', 'U001', 1098.00, 'shipped',   '2026-11-18T09:12:00+00:00', '北京市朝阳区示例路 1 号'),
  ('O1002', 'U002', 1299.00, 'created',   '2026-11-20T14:30:00+00:00', '上海市浦东新区示例路 2 号'),
  ('O1003', 'U001',  918.00, 'delivered', '2026-11-10T03:05:00+00:00', '北京市朝阳区示例路 1 号')
ON DUPLICATE KEY UPDATE `total`=VALUES(`total`), `status`=VALUES(`status`);

-- ---------------- 订单明细 ----------------
CREATE TABLE IF NOT EXISTS `order_items` (
  `id`         BIGINT        NOT NULL AUTO_INCREMENT,
  `order_id`   VARCHAR(32)   NOT NULL,
  `product_id` VARCHAR(32)   NOT NULL,
  `quantity`   INT           NOT NULL DEFAULT 1,
  `unit_price` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_product` (`order_id`, `product_id`),
  CONSTRAINT `fk_order_items_order` FOREIGN KEY (`order_id`) REFERENCES `orders` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `order_items` (`order_id`, `product_id`, `quantity`, `unit_price`) VALUES
  ('O1001', 'P001', 1, 899.00),
  ('O1001', 'P005', 1, 199.00),
  ('O1002', 'P003', 1, 1299.00),
  ('O1003', 'P006', 2, 459.00)
ON DUPLICATE KEY UPDATE `quantity`=VALUES(`quantity`), `unit_price`=VALUES(`unit_price`);

-- ---------------- 审计日志 ----------------
CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id`         BIGINT       NOT NULL AUTO_INCREMENT,
  `user_id`    VARCHAR(32)  NOT NULL DEFAULT '',
  `action`     VARCHAR(64)  NOT NULL DEFAULT '',
  `target`     VARCHAR(64)  NOT NULL DEFAULT '',
  `decision`   VARCHAR(16)  NOT NULL DEFAULT 'allow' COMMENT 'allow/deny',
  `detail`     VARCHAR(255) NOT NULL DEFAULT '',
  `created_at` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_audit_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `audit_logs` (`user_id`, `action`, `target`, `decision`, `detail`) VALUES
  ('A001', 'auth.login',        'token',  'allow', 'demo seed'),
  ('U002', 'api.get_order',     'O1001',  'deny',  '越权访问示例'),
  ('U001', 'api.create_order',  'O1004',  'allow', 'demo seed');
