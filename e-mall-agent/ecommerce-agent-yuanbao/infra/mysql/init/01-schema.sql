CREATE DATABASE IF NOT EXISTS ecommerce_agent DEFAULT CHARACTER SET utf8mb4;
USE ecommerce_agent;

CREATE TABLE users (user_id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL,
  display_name VARCHAR(128), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE sessions (thread_id VARCHAR(128) PRIMARY KEY, user_id VARCHAR(64) NOT NULL,
  tenant_id VARCHAR(64) NOT NULL, state_json LONGTEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP);
CREATE TABLE products (sku VARCHAR(64) PRIMARY KEY, name VARCHAR(255), category VARCHAR(64),
  brand VARCHAR(64), price DECIMAL(10,2), stock INT, rating DECIMAL(3,1), tenant_id VARCHAR(64));
CREATE TABLE orders (order_id VARCHAR(64) PRIMARY KEY, user_id VARCHAR(64), status VARCHAR(32),
  total DECIMAL(10,2), created_at DATETIME, paid TINYINT(1), tenant_id VARCHAR(64));
CREATE TABLE coupons (code VARCHAR(64) PRIMARY KEY, type VARCHAR(32), title VARCHAR(128),
  threshold DECIMAL(10,2), value DECIMAL(10,2), tenant_id VARCHAR(64));
CREATE TABLE approvals (id VARCHAR(64) PRIMARY KEY, tool VARCHAR(64), args_json TEXT,
  reason TEXT, risk VARCHAR(16), status VARCHAR(32), decided_by VARCHAR(64),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, decided_at TIMESTAMP NULL, expires_at TIMESTAMP NULL);
CREATE TABLE idempotency (idem_key VARCHAR(128) PRIMARY KEY, result_json TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ttl_seconds INT DEFAULT 3600);
CREATE TABLE checkpoints (task_id VARCHAR(128) PRIMARY KEY, steps_total INT,
  completed_json TEXT, results_json TEXT, status VARCHAR(32), heartbeat TIMESTAMP);
CREATE TABLE audit_log (id BIGINT AUTO_INCREMENT PRIMARY KEY, trace_id VARCHAR(128),
  user_id VARCHAR(64), tool VARCHAR(64), args_json TEXT, status VARCHAR(32), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE traces (trace_id VARCHAR(128) PRIMARY KEY, root_span_json LONGTEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE eval_cases (case_id VARCHAR(64) PRIMARY KEY, question TEXT, expected_json TEXT, tags VARCHAR(255));
CREATE TABLE eval_runs (id BIGINT AUTO_INCREMENT PRIMARY KEY, case_id VARCHAR(64),
  answer TEXT, scores_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE prompt_registry (prompt_id VARCHAR(64), version INT, content_hash VARCHAR(64),
  content LONGTEXT, stage VARCHAR(16), PRIMARY KEY(prompt_id, version));
CREATE TABLE knowledge_docs (doc_id VARCHAR(128), version INT, chunk_id VARCHAR(160),
  text LONGTEXT, acl_tenant VARCHAR(64), acl_roles VARCHAR(255), PRIMARY KEY(doc_id, version, chunk_id));
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_audit_trace ON audit_log(trace_id);
