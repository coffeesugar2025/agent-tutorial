# 小栈 · 电商智能体（双后端全量版）

> 结合上一版 LangChain 1.5 电商智能体，按《Agent 开发知识点总纲》10 章 + 4 个附录
> 逐条补齐，交付 Vue3 前端 + Python/Java 双后端 + 全套基础设施 + 测试 + 部署脚本。

## 交付物对照

| 要求 | 位置 |
|---|---|
| ① 前端 Vue3（共用） | `frontend/`（`VITE_BACKEND=python\|java` 切换） |
| ① 后端 Python | `backend-python/`（LangChain 1.5.2 + FastAPI + Python 3.12） |
| ① 后端 Java | `backend-java/`（LangChain4j 1.24.0 + Spring Boot 3.3.6 + JDK17） |
| ① RAG | Milvus（`infra/milvus/README.md` + 两端适配器） |
| ① 数据库/缓存/MQ | MySQL / Redis / RabbitMQ（`infra/`） |
| ① 多模型 | DeepSeek / 千问 / OpenAI / GLM / 文心 / Ollama（`infra/llm_gateway.py`、`LlmConfig.java`） |
| ② 技术架构 | `docs/02-技术架构.md` |
| ③ 产品架构 | `docs/01-产品架构.md` |
| ④ 测试用例 | `docs/05-测试体系.md` + `backend-python/tests/` + `backend-java/src/test/` + `tests/` |
| ⑤ 部署脚本 | `infra/docker-compose.yml` + `docs/06-部署手册.md` |
| ★ 知识点覆盖 | `docs/03-知识点全量覆盖矩阵.md`（10 章逐条 → 文件/端点/测试/等级） |
| ★ 双后端契约 | `docs/04-双后端契约.md` + `tests/contract/` |
| ★ 边界 | `docs/07-边界与风险.md` |

## 三分钟离线跑（零外部服务）

```bash
cd backend-python && pip install -r requirements.txt
python -m pytest -q                        # Python 全量（246 passed）
cd .. && python3 scripts/verify_all.py      # 目录/契约/矩阵/compose 校验
python3 tests/contract/check_contract.py   # 双后端路径一致性
python3 tests/ci/gate.py                   # 三重门禁
```

## 全量起服务

```bash
cp infra/.env.example infra/.env
docker compose -f infra/docker-compose.yml up -d --build
bash infra/scripts/smoke.sh
```

## 必读边界

Java 侧**main 源码已用 JDK17 javac 真实编译通过（0 error）**，但 `mvn test` 与 Spring 上下文启动未验证，且 `/v3` 中 9 个端点为契约镜像桩，
业务真值以 Python 为准（见 `docs/04`）；Milvus/MySQL/Redis/RabbitMQ **未实际拉起**
（只做 compose 配置校验，适配器有进程内降级）；真实模型调用需 API Key。
训练执行、OS 级沙盒、A2A/多模态属「契约或明确不适用」，详见 `docs/07`。
