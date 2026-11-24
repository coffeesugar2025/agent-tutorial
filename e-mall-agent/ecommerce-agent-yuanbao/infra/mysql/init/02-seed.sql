USE ecommerce_agent;
INSERT IGNORE INTO users VALUES ('u_1001','t_default','演示用户',NOW()),('u_2002','t_other','另一租户用户',NOW());
INSERT IGNORE INTO products VALUES
 ('SKU-1001','星野 Pro 降噪耳机','数码','星野',899.00,12,4.8,'t_default'),
 ('SKU-2002','云眠 乳胶枕','家居','云眠',299.00,40,4.7,'t_default'),
 ('SKU-4001','拾光 机械键盘 87 键','数码','拾光',549.00,27,4.9,'t_default');
INSERT IGNORE INTO coupons VALUES ('FULL100','full_reduce','满 500 减 100',500.00,100.00,'t_default');
INSERT IGNORE INTO orders VALUES ('EC20261118001','u_1001','运输中',799.00,'2026-11-18 10:00:00',1,'t_default');
