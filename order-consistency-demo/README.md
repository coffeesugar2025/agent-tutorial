# 订单一致性示例：幂等 / 防超卖 / 状态机 / Outbox → RabbitMQ

Spring Boot 3.3.5 + JDK 17 + Spring JDBC(JdbcTemplate) + MySQL 8 + RabbitMQ（spring-boot-starter-amqp）。
一个最小但可运行的「下单 → 支付」链路，四个模式串在同一个本地事务边界上，Outbox 事件**真实投递到 RabbitMQ**，并带 publisher confirm、不可路由检测与消费端幂等。

## 1. 起依赖

```bash
# MySQL 8（表结构由 spring.sql.init 自动执行）
docker run -d --name order-mysql \
  -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=order_demo \
  -p 3306:3306 mysql:8.0

# RabbitMQ（带管理台，15672 / guest guest）
docker run -d --name order-rabbit \
  -p 5672:5672 -p 15672:15672 rabbitmq:3.13-management

# 启动应用（JDK 17+ / Maven 3.8+）
mvn spring-boot:run
# 或：mvn clean package && java -jar target/order-consistency-demo-1.0.0.jar

# 只想跑纯逻辑、不连 broker：
mvn spring-boot:run -Dspring-boot.run.arguments=--outbox.sender=log
```

配置见 `src/main/resources/application.yml`：MySQL `root/root@localhost:3306/order_demo`，RabbitMQ `guest/guest@localhost:5672`。
启动后自动建表 + 插入演示库存（sku 1001 有 100 件），并由 `RabbitAdmin` 声明交换器与队列。

## 2. 试一下

```bash
# 下单：带 Idempotency-Key
curl -s -X POST localhost:8080/orders \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: k-1001' \
  -d '{"skuId":1001,"qty":3}'

# 同一个 key 重发：返回首次响应快照，库存只扣一次、RabbitMQ 只收到一条
curl -s -X POST localhost:8080/orders \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: k-1001' \
  -d '{"skuId":1001,"qty":3}'

# 同一个 key 换 body：400
curl -s -X POST localhost:8080/orders \
  -H 'Content-Type: application/json' -H 'Idempotency-Key: k-1001' \
  -d '{"skuId":1001,"qty":9}'

# 并发压库存：100 件，50 个请求各买 3 件，只会有 33 个成功，其余 409 sold out
seq 1 50 | xargs -P 20 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST localhost:8080/orders -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: burst-{}' -d '{"skuId":1001,"qty":3}'

# 支付：状态机 CREATED -> PAID，再写一条 ORDER_PAID Outbox
curl -s -X POST localhost:8080/orders/1/pay
# 重复支付：422 illegal transition
```

应用日志会依次出现：

```
[outbox] 抢占 -> [rabbit] confirm ack -> UPDATE ... status='SENT'
[consumer] handled type=ORDER_CREATED outboxId=1 aggregateId=1 event={"orderId":1,...}
```

管理台 `http://localhost:15672` 的 `order.exchange` 里能看到两个队列的消息数变化。

## 3. RabbitMQ 这一层做了什么

### 拓扑

```
                    ORDER_CREATED  ──> order.created.q
order.exchange ─┤
 (topic,durable)    ORDER_PAID     ──> order.paid.q
```

`routingKey = eventType`，队列与交换器都 durable，消息 `deliveryMode=PERSISTENT`。
**新增事件类型必须同时在 `RabbitConfig` 里加一条 `Binding`**，否则 mandatory 消息会被 broker return。

### 发送端：三件套缺一不可

| 配置 / 代码 | 作用 |
|---|---|
| `spring.rabbitmq.publisher-confirm-type: correlated` | broker 收妥后回调 `ConfirmCallback` |
| `spring.rabbitmq.publisher-returns: true` + `template.setMandatory(true)` | 消息不可路由时回调 `ReturnsCallback`，而不是静默丢弃 |
| `RabbitMessageSender` 同步 `future.get(timeout)` | **确认成功才返回**；失败抛异常让 Outbox 保持 PENDING 并退避重试 |

最容易踩的坑：**只看 confirm 会把「不可路由」误判为成功** —— broker 对 mandatory 且无匹配 binding 的消息，会先发 `basic.return`，再发 `basic.ack`。示例用 `PublishTracker` 把两个异步回调合并成一个 `CompletableFuture<String>`：return 先把结果置为 `UNROUTABLE`，随后 confirm 的 `complete` 不覆盖它，于是 sender 抛异常、记录不被标记 SENT。`outboxId` 同时用作 `CorrelationData.id` 与消息头，供回调关联。

`spring.rabbitmq.publisher-returns=true` 与 `template.setMandatory(true)` 必须同时开；只开前者不会收到 return。

### 消费端：at-least-once 的兜底

Outbox 天然可能重投：`SENT` 回写失败、confirm 超时、消费处理失败 requeue。`OrderEventConsumer` 用手动 ack + `INSERT IGNORE INTO t_consumed_event(outbox_id, ...)` 去重，重复消息直接 ack 跳过；处理异常 `basicNack(tag,false,true)` 重新入队。

> 示例里「标记已消费」与「业务处理」只做了日志演示；**生产环境必须把两者放进同一个 `@Transactional`**，否则会出现「记了已消费但业务没做」，那才是真正的丢消息。

## 4. 代码地图

| 文件 | 模式 | 关键支点 |
|---|---|---|
| `idem/IdempotencyGuard.java` | 幂等 | `idem_key` 主键冲突抢占 + 请求体 SHA-256 校验 + 同事务回写响应快照 |
| `stock/StockRepository.java` | 防超卖 | `UPDATE ... WHERE available >= ?`，以 affected rows 为唯一判据 |
| `state/OrderStateMachine.java` | 状态机 | 枚举转移表做合法性校验，`WHERE status=?` 做并发 CAS |
| `outbox/OutboxRepository.java` | Outbox | 业务事务内只 INSERT 事件表，绝不发网络请求 |
| `outbox/OutboxDispatcher.java` | Outbox | `FOR UPDATE SKIP LOCKED` 多实例抢占 + 事务外投递 + 指数退避重试 |
| `outbox/OutboxMessage.java` | Outbox | 投递消息模型，`outboxId` 贯穿 confirm / 幂等 |
| `outbox/PublishTracker.java` | RabbitMQ | 合并 confirm 与 return 为一个可同步等待的结果 |
| `outbox/RabbitConfig.java` | RabbitMQ | exchange / queue / binding 声明 + mandatory + 手动 ack 容器 |
| `outbox/RabbitMessageSender.java` | RabbitMQ | 持久化消息 + CorrelationData + 超时等待，失败即抛 |
| `outbox/LoggingMessageSender.java` | 备选 | `outbox.sender=log` 时的纯日志实现，不连 broker |
| `outbox/OrderEventConsumer.java` | 消费幂等 | 手动 ack + `t_consumed_event` 去重 |
| `service/OrderService.java` | 串起来 | 幂等 → 原子扣减 → 建单 → 写 Outbox，一次 `TransactionTemplate` 提交 |

## 5. 整体链路

```
POST /orders (Idempotency-Key)
  │
  ├─ idem_key 命中        → 直接返回首次响应快照（不执行业务）
  └─ 未命中，开启本地事务
       ├─ UPDATE stock ... WHERE available >= qty   ← 行锁 + 条件更新，防超卖
       ├─ INSERT t_order (CREATED)
       ├─ INSERT t_outbox_event (PENDING)            ← 与业务同事务
       └─ UPDATE t_idempotency (SUCCEEDED, response_json)
                    │ COMMIT
                    ▼
  OutboxDispatcher 轮询（SKIP LOCKED 抢占 → PROCESSING）
                    ▼
  RabbitMessageSender.send()
       ├─ 持久化 Message，routingKey=eventType，header 带 outboxId
       ├─ CorrelationData(outboxId) + 等待 confirm / return
       └─ ack 且未 return → UPDATE t_outbox_event SET status='SENT'
                    ▼
  OrderEventConsumer（手动 ack + outbox_id 幂等）
                    ▼
POST /orders/{id}/pay
       └─ 状态机 CREATED→PAID → CAS 更新 → 再写一条 Outbox（ORDER_PAID）
```

## 6. 边界与注意事项

- **幂等**：`Idempotency-Key` 由客户端生成（UUID/业务单号），粒度是「一次业务意图」；业务异常整体回滚，key 自动释放，可安全重试。
- **防超卖**：数据库条件更新是最后防线，不要在 Java 里先 `SELECT` 再 `UPDATE`；扣减与建单必须同事务。
- **状态机**：内存转移表只保证「能不能转」，`WHERE status=?` 才保证并发下「不越过去」，两者缺一不可。
- **Outbox 只保证至少一次**：nack / return / 超时 / `SENT` 回写失败都会重投，消费端必须幂等；生产环境还需归档 `SENT` 记录、给 `retry_count` 设死信阈值、把消费失败改成 DLQ 而非无限 requeue。
- **SQL 方言**：`FOR UPDATE SKIP LOCKED` 需 MySQL 8.0+ / PostgreSQL；`DATE_ADD / DATE_SUB`、`INSERT IGNORE` 为 MySQL 语法。换 H2 / MySQL 5.7 需调整 `OutboxDispatcher` 与消费端 SQL。
- **事务**：`create()` 不标 `@Transactional`，由 `IdempotencyGuard` 的 `TransactionTemplate` 统一包裹，避免幂等记录与业务裂成两个事务；`pay()` 用 `@Transactional`。注意 `@Transactional` 同类自调用会失效。
- 用 `spring-boot-starter-jdbc` 而非 JPA，刻意避开一级缓存/脏检查带来的错觉，让「数据库当前读」的语义显式可见。

## 7. 测试

```bash
mvn test   # OrderStateMachineTest：不依赖数据库的转移合法性单元测试
```
