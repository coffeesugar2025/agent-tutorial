-- ============================================================================
-- 星图商城 · 电商智能体平台  数据库 Schema (MySQL 8.0+)
-- 两套后端（Python / Java）共用同一份库结构
-- ============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE DATABASE IF NOT EXISTS ecom_agent
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE ecom_agent;

-- ---------------------------------------------------------------------------
-- 1. 用户与身份
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sys_user (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  username      VARCHAR(64)  NOT NULL COMMENT '登录名',
  password_hash VARCHAR(128) NOT NULL COMMENT 'BCrypt',
  display_name  VARCHAR(64)  NOT NULL,
  email         VARCHAR(128) DEFAULT NULL,
  roles         VARCHAR(255) NOT NULL DEFAULT 'USER' COMMENT '逗号分隔: USER,ADMIN,OPS',
  status        TINYINT      NOT NULL DEFAULT 1 COMMENT '1启用 0禁用',
  created_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_username (username)
) ENGINE=InnoDB COMMENT='用户';

CREATE TABLE IF NOT EXISTS user_profile (
  user_id          BIGINT      NOT NULL,
  nickname         VARCHAR(64)  DEFAULT NULL,
  phone            VARCHAR(32)  DEFAULT NULL,
  member_level     VARCHAR(16)  NOT NULL DEFAULT 'NORMAL',
  preferred_brands JSON         DEFAULT NULL COMMENT '["Apple","华为"]',
  budget_min       DECIMAL(10,2) DEFAULT NULL,
  budget_max       DECIMAL(10,2) DEFAULT NULL,
  sizes            JSON         DEFAULT NULL COMMENT '{"shoe":"42"}',
  updated_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (user_id)
) ENGINE=InnoDB COMMENT='用户画像（长期记忆的结构化部分）';

CREATE TABLE IF NOT EXISTS user_memory (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  user_id        BIGINT       NOT NULL,
  mem_type       VARCHAR(24)  NOT NULL COMMENT 'SEMANTIC/EPISODIC/PROCEDURAL',
  content        TEXT         NOT NULL,
  importance     DECIMAL(3,2) NOT NULL DEFAULT 0.50,
  source_session BIGINT       DEFAULT NULL,
  vector_id      BIGINT       DEFAULT NULL COMMENT 'Milvus user_memory 主键',
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  expires_at     DATETIME(3)  DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_mem_user (user_id, mem_type, importance DESC)
) ENGINE=InnoDB COMMENT='长期记忆';

-- ---------------------------------------------------------------------------
-- 2. 商品
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS category (
  id        BIGINT      NOT NULL AUTO_INCREMENT,
  name      VARCHAR(64) NOT NULL,
  parent_id BIGINT      NOT NULL DEFAULT 0,
  sort      INT         NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  KEY idx_cat_parent (parent_id)
) ENGINE=InnoDB COMMENT='类目';

CREATE TABLE IF NOT EXISTS product (
  id             BIGINT        NOT NULL AUTO_INCREMENT,
  sku            VARCHAR(64)   NOT NULL,
  title          VARCHAR(255)  NOT NULL,
  subtitle       VARCHAR(255)  DEFAULT NULL,
  brand          VARCHAR(64)   DEFAULT NULL,
  category_id    BIGINT        NOT NULL,
  price          DECIMAL(10,2) NOT NULL,
  original_price DECIMAL(10,2) DEFAULT NULL,
  stock          INT           NOT NULL DEFAULT 0,
  status         TINYINT       NOT NULL DEFAULT 1 COMMENT '1上架 0下架',
  rating         DECIMAL(2,1)  NOT NULL DEFAULT 5.0,
  sales          INT           NOT NULL DEFAULT 0,
  image_url      VARCHAR(512)  DEFAULT NULL,
  attrs          JSON          DEFAULT NULL COMMENT '{"color":"黑","memory":"256G"}',
  description    TEXT          DEFAULT NULL,
  search_text    TEXT          DEFAULT NULL COMMENT '拼装用于全文检索',
  created_at     DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at     DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_product_sku (sku),
  KEY idx_product_cat (category_id, status),
  KEY idx_product_price (price),
  FULLTEXT KEY ft_product (title, subtitle, brand, search_text) WITH PARSER ngram
) ENGINE=InnoDB COMMENT='商品 SPU';

-- ---------------------------------------------------------------------------
-- 3. 订单 / 物流 / 退款
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_info (
  id               BIGINT        NOT NULL AUTO_INCREMENT,
  order_no         VARCHAR(64)   NOT NULL,
  user_id          BIGINT        NOT NULL,
  status           VARCHAR(24)   NOT NULL DEFAULT 'CREATED'
                   COMMENT 'CREATED/PAID/SHIPPED/DELIVERED/FINISHED/CANCELLED/REFUNDING/REFUNDED',
  total_amount     DECIMAL(12,2) NOT NULL DEFAULT 0,
  pay_amount       DECIMAL(12,2) NOT NULL DEFAULT 0,
  receiver_name    VARCHAR(64)   DEFAULT NULL,
  receiver_phone   VARCHAR(32)   DEFAULT NULL,
  receiver_address VARCHAR(512)  DEFAULT NULL,
  created_at       DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  paid_at          DATETIME(3)   DEFAULT NULL,
  shipped_at       DATETIME(3)   DEFAULT NULL,
  finished_at      DATETIME(3)   DEFAULT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_order_no (order_no),
  KEY idx_order_user (user_id, status, created_at DESC)
) ENGINE=InnoDB COMMENT='订单';

CREATE TABLE IF NOT EXISTS order_item (
  id         BIGINT        NOT NULL AUTO_INCREMENT,
  order_id   BIGINT        NOT NULL,
  product_id BIGINT        NOT NULL,
  sku        VARCHAR(64)   NOT NULL,
  title      VARCHAR(255)  NOT NULL,
  price      DECIMAL(10,2) NOT NULL,
  quantity   INT           NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  KEY idx_item_order (order_id)
) ENGINE=InnoDB COMMENT='订单明细';

CREATE TABLE IF NOT EXISTS logistics (
  id           BIGINT       NOT NULL AUTO_INCREMENT,
  order_id     BIGINT       NOT NULL,
  order_no     VARCHAR(64)  NOT NULL,
  company      VARCHAR(64)  DEFAULT NULL,
  tracking_no  VARCHAR(64)  DEFAULT NULL,
  status       VARCHAR(24)  NOT NULL DEFAULT 'PENDING',
  latest_event VARCHAR(255) DEFAULT NULL,
  events       JSON         DEFAULT NULL COMMENT '[{"time":"...","desc":"..."}]',
  updated_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_logistics_order (order_id)
) ENGINE=InnoDB COMMENT='物流';

CREATE TABLE IF NOT EXISTS refund_request (
  id              BIGINT        NOT NULL AUTO_INCREMENT,
  refund_no       VARCHAR(64)   NOT NULL,
  order_id        BIGINT        NOT NULL,
  user_id         BIGINT        NOT NULL,
  reason          VARCHAR(512)  NOT NULL,
  amount          DECIMAL(12,2) NOT NULL,
  status          VARCHAR(24)   NOT NULL DEFAULT 'PENDING_APPROVAL'
                  COMMENT 'PENDING_APPROVAL/APPROVED/REJECTED/PROCESSING/SUCCESS/FAILED',
  idempotency_key VARCHAR(128)  NOT NULL,
  approval_id     BIGINT        DEFAULT NULL,
  created_at      DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_refund_no (refund_no),
  UNIQUE KEY uk_refund_idem (idempotency_key),
  KEY idx_refund_user (user_id, status)
) ENGINE=InnoDB COMMENT='退款申请';

-- ---------------------------------------------------------------------------
-- 4. 会话 / 消息 / 审批
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_session (
  id              BIGINT      NOT NULL AUTO_INCREMENT,
  user_id         BIGINT      NOT NULL,
  title           VARCHAR(255) NOT NULL DEFAULT '新会话',
  agent_type      VARCHAR(24) NOT NULL DEFAULT 'SUPERVISOR',
  status          VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
  summary         TEXT        DEFAULT NULL COMMENT '滚动摘要',
  created_at      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  last_message_at DATETIME(3) DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_session_user (user_id, last_message_at DESC)
) ENGINE=InnoDB COMMENT='会话';

CREATE TABLE IF NOT EXISTS chat_message (
  id          BIGINT      NOT NULL AUTO_INCREMENT,
  session_id  BIGINT      NOT NULL,
  role        VARCHAR(16) NOT NULL COMMENT 'user/assistant/system/tool',
  content     MEDIUMTEXT  DEFAULT NULL,
  agent_type  VARCHAR(24) DEFAULT NULL,
  tool_calls  JSON        DEFAULT NULL,
  citations   JSON        DEFAULT NULL,
  token_in    INT         NOT NULL DEFAULT 0,
  token_out   INT         NOT NULL DEFAULT 0,
  cost_cents  INT         NOT NULL DEFAULT 0,
  trace_id    VARCHAR(64) DEFAULT NULL,
  created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_msg_session (session_id, id),
  KEY idx_msg_trace (trace_id)
) ENGINE=InnoDB COMMENT='消息';

CREATE TABLE IF NOT EXISTS approval_task (
  id               BIGINT      NOT NULL AUTO_INCREMENT,
  session_id       BIGINT      NOT NULL,
  message_id       BIGINT      DEFAULT NULL,
  user_id          BIGINT      NOT NULL,
  action_type      VARCHAR(48) NOT NULL COMMENT 'CREATE_REFUND/CHANGE_ADDRESS/CANCEL_ORDER...',
  title            VARCHAR(255) NOT NULL,
  detail           JSON        DEFAULT NULL,
  risk             VARCHAR(16) NOT NULL DEFAULT 'IRREVERSIBLE',
  status           VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/APPROVED/REJECTED/EXPIRED',
  decision_comment VARCHAR(512) DEFAULT NULL,
  decided_by       BIGINT      DEFAULT NULL,
  created_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  expires_at       DATETIME(3) DEFAULT NULL,
  decided_at       DATETIME(3) DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_approval_user (user_id, status),
  KEY idx_approval_session (session_id)
) ENGINE=InnoDB COMMENT='人工审批任务';

-- ---------------------------------------------------------------------------
-- 5. 知识库
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_document (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  title       VARCHAR(255) NOT NULL,
  doc_type    VARCHAR(32)  NOT NULL COMMENT 'POLICY/MANUAL/FAQ/PRODUCT_DOC',
  source      VARCHAR(512) DEFAULT NULL,
  visibility  VARCHAR(24)  NOT NULL DEFAULT 'PUBLIC' COMMENT 'PUBLIC/INTERNAL/ADMIN',
  status      VARCHAR(16)  NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/INDEXING/READY/FAILED',
  version     INT          NOT NULL DEFAULT 1,
  chunk_count INT          NOT NULL DEFAULT 0,
  checksum    VARCHAR(64)  DEFAULT NULL,
  created_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  deleted_at  DATETIME(3)  DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_doc_status (status),
  KEY idx_doc_type (doc_type, visibility)
) ENGINE=InnoDB COMMENT='知识文档（软删除支持撤销）';

CREATE TABLE IF NOT EXISTS knowledge_chunk (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  document_id   BIGINT       NOT NULL,
  chunk_no      INT          NOT NULL,
  content       TEXT         NOT NULL,
  parent_content MEDIUMTEXT  DEFAULT NULL COMMENT '父子块：命中子块返回父块',
  token_count   INT          NOT NULL DEFAULT 0,
  metadata      JSON         DEFAULT NULL,
  created_at    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_chunk_doc (document_id, chunk_no)
) ENGINE=InnoDB COMMENT='知识切片';

CREATE TABLE IF NOT EXISTS knowledge_job (
  id          BIGINT      NOT NULL AUTO_INCREMENT,
  document_id BIGINT      NOT NULL,
  job_type    VARCHAR(32) NOT NULL COMMENT 'INDEX/REINDEX/DELETE',
  status      VARCHAR(16) NOT NULL DEFAULT 'QUEUED' COMMENT 'QUEUED/RUNNING/SUCCESS/FAILED',
  progress    INT         NOT NULL DEFAULT 0,
  error       TEXT        DEFAULT NULL,
  created_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at  DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_job_doc (document_id)
) ENGINE=InnoDB COMMENT='索引作业';

-- ---------------------------------------------------------------------------
-- 6. 可观测性
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_trace (
  id               BIGINT       NOT NULL AUTO_INCREMENT,
  trace_id         VARCHAR(64)  NOT NULL,
  session_id       BIGINT       NOT NULL,
  user_id          BIGINT       NOT NULL,
  agent_type       VARCHAR(24)  DEFAULT NULL,
  question         TEXT         DEFAULT NULL,
  answer           MEDIUMTEXT   DEFAULT NULL,
  status           VARCHAR(16)  NOT NULL DEFAULT 'RUNNING' COMMENT 'RUNNING/SUCCESS/FAILED/INTERRUPTED',
  total_latency_ms INT          NOT NULL DEFAULT 0,
  total_cost_cents INT          NOT NULL DEFAULT 0,
  step_count       INT          NOT NULL DEFAULT 0,
  created_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_trace_id (trace_id),
  KEY idx_trace_session (session_id)
) ENGINE=InnoDB COMMENT='链路追踪根节点';

CREATE TABLE IF NOT EXISTS agent_span (
  id             BIGINT      NOT NULL AUTO_INCREMENT,
  trace_id       VARCHAR(64) NOT NULL,
  span_id        VARCHAR(64) NOT NULL,
  parent_span_id VARCHAR(64) DEFAULT NULL,
  name           VARCHAR(128) NOT NULL,
  span_type      VARCHAR(24) NOT NULL COMMENT 'LLM/TOOL/RETRIEVAL/AGENT/GUARDRAIL',
  seq            INT         NOT NULL DEFAULT 0,
  input          JSON        DEFAULT NULL,
  output         JSON        DEFAULT NULL,
  latency_ms     INT         NOT NULL DEFAULT 0,
  status         VARCHAR(16) NOT NULL DEFAULT 'OK',
  error          TEXT        DEFAULT NULL,
  started_at     DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_span_trace (trace_id, seq),
  UNIQUE KEY uk_span_id (span_id)
) ENGINE=InnoDB COMMENT='链路追踪 span';

CREATE TABLE IF NOT EXISTS llm_call (
  id                BIGINT      NOT NULL AUTO_INCREMENT,
  trace_id          VARCHAR(64) DEFAULT NULL,
  span_id           VARCHAR(64) DEFAULT NULL,
  provider          VARCHAR(32) NOT NULL,
  model             VARCHAR(64) NOT NULL,
  prompt_tokens     INT         NOT NULL DEFAULT 0,
  completion_tokens INT         NOT NULL DEFAULT 0,
  cached_tokens     INT         NOT NULL DEFAULT 0,
  cost_cents        INT         NOT NULL DEFAULT 0,
  latency_ms        INT         NOT NULL DEFAULT 0,
  status            VARCHAR(16) NOT NULL DEFAULT 'OK',
  created_at        DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_llm_trace (trace_id),
  KEY idx_llm_model (model, created_at)
) ENGINE=InnoDB COMMENT='模型调用账单';

CREATE TABLE IF NOT EXISTS audit_log (
  id         BIGINT      NOT NULL AUTO_INCREMENT,
  user_id    BIGINT      NOT NULL,
  action     VARCHAR(64) NOT NULL,
  target     VARCHAR(128) DEFAULT NULL,
  detail     JSON        DEFAULT NULL,
  ip         VARCHAR(64) DEFAULT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_audit_user (user_id, created_at DESC)
) ENGINE=InnoDB COMMENT='审计日志';

-- ---------------------------------------------------------------------------
-- 7. 评测
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_run (
  id              BIGINT      NOT NULL AUTO_INCREMENT,
  suite           VARCHAR(64) NOT NULL,
  status          VARCHAR(16) NOT NULL DEFAULT 'RUNNING',
  total           INT         NOT NULL DEFAULT 0,
  passed          INT         NOT NULL DEFAULT 0,
  pass_rate       DECIMAL(5,4) NOT NULL DEFAULT 0,
  pass_k          DECIMAL(5,4) NOT NULL DEFAULT 0,
  repeat_times    INT         NOT NULL DEFAULT 1,
  avg_cost_cents  INT         NOT NULL DEFAULT 0,
  avg_latency_ms  INT         NOT NULL DEFAULT 0,
  report          JSON        DEFAULT NULL,
  started_at      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  finished_at     DATETIME(3) DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_eval_suite (suite, started_at DESC)
) ENGINE=InnoDB COMMENT='评测批次';

CREATE TABLE IF NOT EXISTS eval_case_result (
  id       BIGINT      NOT NULL AUTO_INCREMENT,
  run_id   BIGINT      NOT NULL,
  case_id  VARCHAR(64) NOT NULL,
  question TEXT        NOT NULL,
  expected TEXT        DEFAULT NULL,
  actual   MEDIUMTEXT  DEFAULT NULL,
  passed   TINYINT     NOT NULL DEFAULT 0,
  score    DECIMAL(4,3) NOT NULL DEFAULT 0,
  attempts INT         NOT NULL DEFAULT 1,
  detail   JSON        DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_case_run (run_id)
) ENGINE=InnoDB COMMENT='评测用例结果';

-- ---------------------------------------------------------------------------
-- 8. 运行时支撑：幂等、异步任务、长任务检查点、Prompt 版本
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS idempotency_record (
  idem_key   VARCHAR(160) NOT NULL,
  scope      VARCHAR(64)  NOT NULL,
  result     JSON         DEFAULT NULL,
  created_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  expires_at DATETIME(3)  DEFAULT NULL,
  PRIMARY KEY (idem_key)
) ENGINE=InnoDB COMMENT='幂等记录';

CREATE TABLE IF NOT EXISTS async_task (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  task_type  VARCHAR(48)  NOT NULL,
  payload    JSON         NOT NULL,
  status     VARCHAR(16)  NOT NULL DEFAULT 'QUEUED' COMMENT 'QUEUED/RUNNING/SUCCESS/FAILED/DEAD',
  retry      INT          NOT NULL DEFAULT 0,
  max_retry  INT          NOT NULL DEFAULT 3,
  error      TEXT         DEFAULT NULL,
  created_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_task_status (status, created_at)
) ENGINE=InnoDB COMMENT='异步任务（RabbitMQ 落库兜底）';

CREATE TABLE IF NOT EXISTS agent_checkpoint (
  id         BIGINT      NOT NULL AUTO_INCREMENT,
  session_id BIGINT      NOT NULL,
  trace_id   VARCHAR(64) NOT NULL,
  step_no    INT         NOT NULL,
  state      JSON        NOT NULL COMMENT '可重放状态快照',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_ckpt (trace_id, step_no),
  KEY idx_ckpt_session (session_id)
) ENGINE=InnoDB COMMENT='长任务检查点 / 可重放';

CREATE TABLE IF NOT EXISTS prompt_template (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  code       VARCHAR(64)  NOT NULL,
  version    INT          NOT NULL DEFAULT 1,
  content    MEDIUMTEXT   NOT NULL,
  status     VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE' COMMENT 'DRAFT/ACTIVE/ARCHIVED',
  created_at DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uk_prompt_code_ver (code, version)
) ENGINE=InnoDB COMMENT='Prompt 版本管理';

SET FOREIGN_KEY_CHECKS = 1;
