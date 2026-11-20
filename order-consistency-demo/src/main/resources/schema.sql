CREATE TABLE IF NOT EXISTS t_idempotency (
  idem_key      VARCHAR(128) PRIMARY KEY,
  request_hash  CHAR(64)      NOT NULL,
  status        VARCHAR(16)   NOT NULL COMMENT 'IN_PROGRESS / SUCCEEDED',
  response_json TEXT,
  created_at    DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS t_sku_stock (
  sku_id     BIGINT PRIMARY KEY,
  available  INT NOT NULL,
  version    BIGINT NOT NULL DEFAULT 0,
  CHECK (available >= 0)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS t_order (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT,
  sku_id      BIGINT NOT NULL,
  qty         INT    NOT NULL,
  status      VARCHAR(24) NOT NULL,
  created_at  DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at  DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS t_outbox_event (
  id             BIGINT PRIMARY KEY AUTO_INCREMENT,
  aggregate_type VARCHAR(64)  NOT NULL,
  aggregate_id   VARCHAR(64)  NOT NULL,
  event_type     VARCHAR(64)  NOT NULL,
  payload        TEXT         NOT NULL,
  status         VARCHAR(16)  NOT NULL COMMENT 'PENDING / PROCESSING / SENT',
  retry_count    INT          NOT NULL DEFAULT 0,
  next_retry_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  locked_at      DATETIME(3)  NULL,
  created_at     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  INDEX idx_outbox_pending (status, next_retry_at)
) ENGINE=InnoDB;

-- 消费端幂等：Outbox 是 at-least-once，重复投递靠 outbox_id 去重
CREATE TABLE IF NOT EXISTS t_consumed_event (
  outbox_id   BIGINT PRIMARY KEY,
  event_type  VARCHAR(64) NOT NULL,
  consumed_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
) ENGINE=InnoDB;
