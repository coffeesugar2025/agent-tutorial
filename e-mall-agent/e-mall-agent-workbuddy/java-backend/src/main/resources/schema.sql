-- MySQL 8 初始化脚本（可选，默认由 JPA ddl-auto + DataSeeder 完成）。
-- 手工初始化：mysql -uroot -p ecom < schema.sql
-- 注意：MySQL 8 支持 INSERT IGNORE，重复执行不会产生重复种子数据。

CREATE TABLE IF NOT EXISTS products (
  id          VARCHAR(64)  NOT NULL PRIMARY KEY,
  name        VARCHAR(255) NOT NULL,
  category    VARCHAR(64)  NOT NULL,
  price       DECIMAL(12,2) NOT NULL,
  stock       INT NOT NULL DEFAULT 0,
  tags        VARCHAR(512) NOT NULL DEFAULT '',
  description VARCHAR(1024) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS orders (
  id          VARCHAR(64)  NOT NULL PRIMARY KEY,
  customer_id VARCHAR(64)  NOT NULL,
  total       DECIMAL(12,2) NOT NULL,
  status      VARCHAR(32)  NOT NULL DEFAULT 'created',
  created_at  VARCHAR(40)  NOT NULL,
  address     VARCHAR(512) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS order_items (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_id    VARCHAR(64) NOT NULL,
  product_id  VARCHAR(64) NOT NULL,
  quantity    INT NOT NULL,
  unit_price  DECIMAL(12,2) NOT NULL,
  CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS users (
  id       VARCHAR(64) NOT NULL PRIMARY KEY,
  name     VARCHAR(128) NOT NULL,
  role     VARCHAR(32)  NOT NULL DEFAULT 'customer',
  password VARCHAR(128) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS audit_logs (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  actor      VARCHAR(64) NOT NULL,
  action     VARCHAR(128) NOT NULL,
  target     VARCHAR(128) NOT NULL DEFAULT '',
  decision   VARCHAR(32)  NOT NULL DEFAULT 'allow',
  detail     VARCHAR(512) NOT NULL DEFAULT '',
  created_at VARCHAR(40)  NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO users (id, name, role, password) VALUES
  ('U001', '张三', 'customer', '123456'),
  ('U002', '李四', 'customer', '123456'),
  ('S001', '王客服', 'service',  '123456'),
  ('A001', '管理员', 'admin',    '123456');

INSERT IGNORE INTO products (id, name, category, price, stock, tags, description) VALUES
  ('P001', '无线降噪耳机 Pro', '数码', 899.00,  12, '音频,热销,降噪', '40小时续航，主动降噪，适合通勤与办公。'),
  ('P002', '便携咖啡机',       '家居', 359.00,  5,  '咖啡,便携', '手压萃取，随行制作意式浓缩。'),
  ('P003', '人体工学椅',       '家具', 1299.00, 3,  '办公,护腰', '网布透气，腰托可调，久坐友好。'),
  ('P004', '智能手表 S2',      '数码', 1099.00, 20, '穿戴,健康', '心率血氧监测，14天续航。'),
  ('P005', '移动电源 20000mAh','数码', 199.00,  50, '充电,出行', '22.5W 快充，可带上飞机。'),
  ('P006', '机械键盘 87键',    '数码', 459.00,  8,  '键盘,办公', '茶轴手感，紧凑布局，支持热插拔。'),
  ('P007', '空气循环扇',       '家电', 299.00,  0,  '风扇,静音', '直流变频，低噪循环送风。'),
  ('P008', '保温杯 500ml',     '家居', 129.00,  100,'水杯,保温', '316不锈钢，12小时保温。');

INSERT IGNORE INTO orders (id, customer_id, total, status, created_at, address) VALUES
  ('O1001', 'U001', 1098.00, 'shipped',    '2026-11-18T09:12:00+00:00', '北京市朝阳区示例路 1 号'),
  ('O1002', 'U002', 1299.00, 'created',    '2026-11-20T14:30:00+00:00', '上海市浦东新区示例路 2 号'),
  ('O1003', 'U001', 918.00,  'delivered',  '2026-11-10T03:05:00+00:00', '北京市朝阳区示例路 1 号');

INSERT IGNORE INTO order_items (order_id, product_id, quantity, unit_price) VALUES
  ('O1001', 'P001', 1, 899.00),
  ('O1001', 'P005', 1, 199.00),
  ('O1002', 'P003', 1, 1299.00),
  ('O1003', 'P006', 2, 459.00);
