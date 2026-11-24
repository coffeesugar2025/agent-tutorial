#!/usr/bin/env python3
"""交付前总校验：目录 / 契约 / compose / 知识点矩阵覆盖率 / 测试计数。"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
errors: list[str] = []


def need(p: str) -> None:
    if not (ROOT / p).exists():
        errors.append(f"missing: {p}")


for p in ["backend-python/app/main.py", "backend-python/app/api/routes_v3.py",
          "backend-java/pom.xml", "backend-java/src/main/java/com/xiaozhan/agent/AgentApplication.java",
          "frontend/src/api/backend.ts", "infra/docker-compose.yml",
          "docs/01-产品架构.md", "docs/02-技术架构.md",
          "docs/03-知识点全量覆盖矩阵.md", "docs/04-双后端契约.md",
          "docs/05-测试体系.md", "docs/06-部署手册.md", "docs/07-边界与风险.md",
          "tests/contract/openapi-contract.json", "tests/contract/check_contract.py",
          "tests/ci/agent-ci.yml", "tests/ci/gate.py"]:
    need(p)

contract = json.loads((ROOT / "tests/contract/openapi-contract.json").read_text(encoding="utf-8"))
print("contract shared paths:", len(contract["shared_paths"]))

# 知识点矩阵覆盖率：每章必须有映射行
matrix = (ROOT / "docs/03-知识点全量覆盖矩阵.md").read_text(encoding="utf-8")
chapters = [f"第 {i} 章" for i in range(10)]
missing_ch = [c for c in chapters if c not in matrix]
print("chapters in matrix:", 10 - len(missing_ch), "/ 10")
if missing_ch:
    errors.append(f"matrix missing chapters: {missing_ch}")

# 测试用例计数
n_py = 0
for f in (ROOT / "backend-python/tests").glob("test_*.py"):
    n_py += len(re.findall(r"^def (test_\w+)\(", f.read_text(encoding="utf-8"), re.M))
n_java = len(re.findall(r"@Test(?!Configuration)\b", (ROOT / "backend-java/src/test/java/com/xiaozhan/agent/JavaContractTests.java")
                        .read_text(encoding="utf-8")))
print("python test funcs:", n_py, "| java @Test:", n_java)

# ---- 复盘修复的固化检查（防止再次退化）----
checks = {
    "retry_classification_wired": ("backend-python/app/capabilities/reliability.py", "classify_errors"),
    "retry_regression_test": ("backend-python/tests/test_retry_classification.py", "test_validation_error_is_not_retried"),
    "vite_proxy_java": ("frontend/vite.config.ts", "/api/java"),
    "vite_proxy_python": ("frontend/vite.config.ts", "/api/py"),
    "console_panel_mounted": ("frontend/src/App.vue", "ConsolePanel"),
}
for name, (f, token) in checks.items():
    if not (ROOT / f).exists() or token not in (ROOT / f).read_text(encoding="utf-8"):
        errors.append(f"regression check failed: {name}")
for v in ["CapabilityPanel", "ApprovalCenter", "TraceReplay", "EvalDashboard",
          "CostDashboard", "CitationView"]:
    if not (ROOT / f"frontend/src/views/{v}.vue").exists():
        errors.append(f"missing view: {v}")
try:
    import yaml
    yaml.safe_load((ROOT / "infra/otel/otel-collector-config.yaml").read_text(encoding="utf-8"))
    env_example = (ROOT / "infra/.env.example").read_text(encoding="utf-8")
    compose_src = (ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8")
    if "MILVUS_HOST=milvus-standalone" not in env_example or "MILVUS_HOST: milvus-standalone" not in compose_src:
        errors.append("milvus host mismatch")
except Exception as exc:
    errors.append(f"otel/host parse: {exc}")
print("regression checks:", 5 + 6 + 2, "items")

# ---- 第三轮复盘固化：防止「写了模块没接进系统」复发 ----
r3 = {
    "mysql_engine_actually_used": ("backend-python/app/infra/adapters.py", "_run_remote"),
    "milvus_ping_on_init": ("backend-python/app/infra/adapters.py", "list_collections()"),
    "milvus_search_fallback": ("backend-python/app/infra/adapters.py", "_last_error"),
    "redis_runtime_drop": ("backend-python/app/infra/adapters.py", "self._redis = None"),
    "mq_runtime_drop": ("backend-python/app/infra/adapters.py", "self._conn = None"),
    "msgbus_ch_declared": ("backend-python/app/infra/adapters.py", "self._ch = None"),
    "adapter_realpath_tests": ("backend-python/tests/test_infra_adapters_realpath.py", "test_relational_execute_and_query_roundtrip"),
    "frontend_no_template_assertion": ("frontend/src/views/ConsolePanel.vue", "activeComp"),
    "frontend_app_styles": ("frontend/src/App.vue", ".console-toggle"),
    "rabbitmq_definitions_loaded": ("infra/rabbitmq/rabbitmq.conf", "management.load_definitions"),
    "minio_root_user": ("infra/docker-compose.yml", "MINIO_ROOT_USER"),
    "java_aiservice_import": ("backend-java/src/main/java/com/xiaozhan/agent/ai/ShoppingAssistant.java", "dev.langchain4j.service.spring.AiService"),
    "java_verify_script": ("backend-java/scripts/verify_compile.sh", "JAVAC COMPILE: PASS"),
}
for name, (f, token) in r3.items():
    if not (ROOT / f).exists() or token not in (ROOT / f).read_text(encoding="utf-8"):
        errors.append(f"r3 regression check failed: {name}")
print("r3 regression checks:", len(r3), "items")

# compose YAML 语法
try:
    import yaml
    compose = yaml.safe_load((ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8"))
    print("compose services:", len(compose.get("services", {})))
except Exception as exc:
    errors.append(f"compose parse: {exc}")

print("RESULT:", "PASS" if not errors else "FAIL")
for e in errors:
    print("  -", e)
sys.exit(0 if not errors else 1)
