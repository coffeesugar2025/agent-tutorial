# Java 后端 · langchain4j 1.24.0 + Spring Boot 3 + JDK17

与 `backend-python` 实现**同一份 HTTP 契约**（`/health`、`/v1/*`、`/v2/*`、`/v3/*`），
前端通过 `VITE_BACKEND=python|java` 切换，无需改业务代码。

## 已核实的版本事实
- langchain4j **1.24.0**（2026-11-18 稳定版）确实存在，BOM 为 `dev.langchain4j:langchain4j-bom:1.24.0`。
- **1.x 破坏性改名**：`ChatLanguageModel` → `ChatModel`，`StreamingChatLanguageModel` → `StreamingChatModel`。
  照 2024 年博客抄 `ChatLanguageModel` 会直接编译失败，本仓库全部用 `ChatModel`。
- Spring Boot 3.x 用 `langchain4j-spring-boot-starter` + `langchain4j-open-ai-spring-boot-starter`；
  Boot 4 才用 `-spring-boot4-starter` 后缀。**两个 starter 都要显式声明**，否则 `@AiService`/`@Tool` 注解不生效。
- 同类型多个 `ChatModel` bean 直接注入会导致启动失败 → 本仓库只暴露一个 `@Primary`，
  其余供应商放进 `Map` 由 `LlmRouter` 选择，`@AiService(wiringMode=EXPLICIT, chatModel="primaryChatModel")` 显式绑定。
- 1.24.0 新增 `langchain4j-test` 的公开 `ChatModel`/`EmbeddingModel` Mock，离线单测不花 token（已在 pom 引入）。

## 本地构建
```bash
cd backend-java
mvn -q -DskipTests package
mvn test                       # 单元 + MockMvc 契约测试
java -jar target/*.jar
```
> **本沙盒只有 JDK 11、无 javac/mvn，Java 侧未编译验证**（见 `docs/07-边界与风险.md`）。
> pom、源码结构、注解坐标已按官方 1.24.0 语义编写，需在 JDK17 + Maven 3.8+ 环境编译。

## 分层
| 层 | 文件 |
|---|---|
| AI Service | `ai/ShoppingAssistant.java`（@AiService + @SystemMessage + @MemoryId） |
| 工具 | `ai/OrderTools.java`（@Tool/@P，含「何时不该用」与稳定错误码） |
| 模型网关 | `config/LlmConfig.java`、`service/LlmRouter.java` |
| 决策 / 编排 | `service/DecisionEngine`、`PlanningService` |
| 安全 | `service/InjectionGuard`、`AclService` |
| RAG | `service/RagService`（Milvus + ACL + 混合 + 引用） |
| 可靠性 | `service/ReliabilityService`、`HitlService`、`CostCacheService` |
| 可观测 | `service/ObservabilityService`（Micrometer + OTel） |
| 基础设施 | `mq/AgentEvents`（RabbitMQ topic）、`application.yml`（MySQL/Redis/Milvus） |
| 契约测试 | `src/test/java/.../JavaContractTests.java` |
