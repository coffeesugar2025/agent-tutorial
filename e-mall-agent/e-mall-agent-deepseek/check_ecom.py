import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
errors = []
notes = []


def err(msg):
    errors.append(msg)


def ok(msg):
    notes.append(msg)


# ---------------------------------------------------------------------------
# 1. YAML compose files
# ---------------------------------------------------------------------------
try:
    import yaml
except ImportError:
    yaml = None

REQUIRED_SERVICES = {
    "mysql", "redis", "rabbitmq", "etcd", "minio", "milvus",
    "backend-python", "backend-java", "frontend",
}
INFRA_SERVICES = {"mysql", "redis", "rabbitmq", "etcd", "minio", "milvus"}


def interp_vars(text):
    found = []
    for m in re.finditer(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)(:[?-][^}]*)?\}", text):
        found.append((m.group(1), m.group(2) is not None))
    return found


compose_docs = {}
for rel in ("deploy/docker-compose.yml", "deploy/docker-compose.infra.yml"):
    p = ROOT / rel
    if not p.exists():
        err(f"missing {rel}")
        continue
    text = p.read_text(encoding="utf-8")
    if yaml is None:
        ok(f"{rel}: pyyaml missing, skipped")
        continue
    try:
        doc = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001
        err(f"{rel}: YAML parse error: {exc}")
        continue
    compose_docs[rel] = doc
    if "version" in doc:
        err(f"{rel}: deprecated 'version' key present")
    for name, svc in doc["services"].items():
        if "links" in svc:
            err(f"{rel}: service {name} uses deprecated 'links'")
        if "\t" in text:
            err(f"{rel}: contains tab characters")
    services = set(doc["services"])
    expected = REQUIRED_SERVICES if rel.endswith("docker-compose.yml") else INFRA_SERVICES
    missing = expected - services
    if missing:
        err(f"{rel}: missing services {sorted(missing)}")
    extra = services - expected
    if extra:
        ok(f"{rel}: extra services {sorted(extra)}")
    if doc["networks"]["ecom-net"].get("name") != "ecom-net":
        err(f"{rel}: network name must be ecom-net")
    vols = doc.get("volumes") or {}
    for v in ("mysql-data", "redis-data", "rabbitmq-data", "etcd-data", "minio-data", "milvus-data"):
        if v not in vols:
            err(f"{rel}: missing volume {v}")
    ok(f"{rel}: services={sorted(services)}")

# SSE + required infra details in nginx conf
nginx = (ROOT / "deploy/nginx/nginx.conf").read_text(encoding="utf-8")
for needle in (
    "proxy_buffering off;",
    "proxy_cache off;",
    "proxy_read_timeout 300s;",
    "proxy_set_header Connection '';",
    "chunked_transfer_encoding on;",
    "backend_python",
    "backend_java",
):
    if needle not in nginx:
        err(f"nginx.conf missing: {needle}")
if nginx.count("{") != nginx.count("}"):
    err("nginx.conf braces unbalanced")
ok(f"nginx.conf: braces={nginx.count('{')}, len={len(nginx)}")

# env vars referenced without default must exist in .env.example
env_text = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")
env_keys = []
for line in env_text.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if "=" not in line:
        err(f".env.example bad line: {line}")
        continue
    k = line.split("=", 1)[0]
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", k):
        err(f".env.example bad key casing: {k}")
    if "export " in line:
        err(f".env.example uses export: {line}")
    env_keys.append(k)
dups = {k for k in env_keys if env_keys.count(k) > 1}
if dups:
    err(f".env.example duplicate keys: {sorted(dups)}")
ok(f".env.example: {len(env_keys)} keys")

docs00_required = [
    "APP_ENV", "MYSQL_HOST", "MYSQL_PORT", "MYSQL_DB", "MYSQL_USER", "MYSQL_PASSWORD",
    "REDIS_HOST", "REDIS_PORT", "REDIS_PASSWORD", "REDIS_DB",
    "RABBITMQ_HOST", "RABBITMQ_PORT", "RABBITMQ_USER", "RABBITMQ_PASSWORD", "RABBITMQ_VHOST",
    "MILVUS_HOST", "MILVUS_PORT", "MILVUS_COLLECTION_PREFIX",
    "LLM_PRIMARY", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
    "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "QWEN_MODEL", "QWEN_FAST_MODEL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "OLLAMA_BASE_URL", "OLLAMA_MODEL",
    "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_DIM", "RERANK_PROVIDER",
    "JWT_SECRET", "MAX_STEPS", "MAX_TOKEN_BUDGET", "TASK_TIMEOUT_SECONDS",
    "APPROVAL_AMOUNT_THRESHOLD_CENTS", "RATE_LIMIT_PER_MINUTE", "MOCK_LLM", "MILVUS_TOKEN",
]
missing_env = [k for k in docs00_required if k not in env_keys]
if missing_env:
    err(f".env.example missing docs/00 vars: {missing_env}")

for rel, doc in compose_docs.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for var, has_default in interp_vars(text):
        if not has_default and var not in env_keys:
            err(f"{rel}: ${{{var}}} has no default and is not in .env.example")

# compose key wiring checks
if "deploy/docker-compose.yml" in compose_docs:
    doc = compose_docs["deploy/docker-compose.yml"]
    py = doc["services"]["backend-python"]["environment"]
    jv = doc["services"]["backend-java"]["environment"]
    if py.get("SERVER_PORT") != "${APP_PORT_PYTHON:-8000}":
        err("python SERVER_PORT wiring wrong")
    if jv.get("SERVER_PORT") != "${APP_PORT_JAVA:-8080}":
        err("java SERVER_PORT wiring wrong")
    for name in ("backend-python", "backend-java"):
        for dep in ("mysql", "redis", "rabbitmq", "milvus"):
            cond = doc["services"][name]["depends_on"].get(dep, {}).get("condition")
            if cond != "service_healthy":
                err(f"{name} depends_on {dep} condition={cond}")
    if doc["services"]["mysql"]["healthcheck"]["test"][0] != "CMD-SHELL":
        err("mysql healthcheck test style unexpected")
    mnt = doc["services"]["mysql"]["volumes"][0]
    if "mysql/init" not in mnt:
        err("mysql init mount missing")
    fe = doc["services"]["frontend"]
    if fe["volumes"][0].split(":")[1] != "/etc/nginx/conf.d/default.conf":
        err("frontend nginx.conf mount target wrong")

# ---------------------------------------------------------------------------
# 2. seed SQL
# ---------------------------------------------------------------------------
sql = (ROOT / "deploy/mysql/init/02-seed.sql").read_text(encoding="utf-8")
if sql.count("'") % 2 != 0:
    err("seed.sql has odd number of single quotes")

JSON_COLS = {
    "attrs", "detail", "events", "tool_calls", "citations", "metadata", "report",
    "payload", "state", "result", "input", "output", "preferred_brands", "sizes",
}


def split_top_level(s):
    """Split a VALUES tuple body on top-level commas, honouring quotes/parens."""
    out, cur, depth, inq, i = [], "", 0, False, 0
    while i < len(s):
        c = s[i]
        if inq:
            cur += c
            if c == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    cur += "'"
                    i += 1
                else:
                    inq = False
        else:
            if c == "'":
                inq = True
                cur += c
            elif c in "([{":
                depth += 1
                cur += c
            elif c in ")]}":
                depth -= 1
                cur += c
            elif c == "," and depth == 0:
                out.append(cur)
                cur = ""
            else:
                cur += c
        i += 1
    out.append(cur)
    return [v.strip() for v in out]


def unquote(v):
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


table_counts = {}
insert_re = re.compile(r"INSERT INTO (\w+)\s*\(([^)]*)\)\s*VALUES\s*", re.I)
pos = 0
while True:
    m = insert_re.search(sql, pos)
    if not m:
        break
    table = m.group(1)
    cols = [c.strip() for c in m.group(2).split(",")]
    i = m.end()
    rows = 0
    while True:
        while i < len(sql) and sql[i] in " \r\n\t":
            i += 1
        if i >= len(sql) or sql[i] != "(":
            break
        start = i + 1
        depth, inq = 0, False
        while i < len(sql):
            c = sql[i]
            if inq:
                if c == "'":
                    if sql[i + 1] == "'":
                        i += 1
                    else:
                        inq = False
            else:
                if c == "'":
                    inq = True
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        break
            i += 1
        body = sql[start:i]
        vals = split_top_level(body)
        rows += 1
        if len(vals) != len(cols):
            err(f"seed {table}: row {rows} has {len(vals)} values, expected {len(cols)}")
        for col, val in zip(cols, vals):
            if col in JSON_COLS:
                raw = unquote(val)
                if raw in ("NULL",):
                    continue
                try:
                    json.loads(raw)
                except Exception:
                    unquote_ok = False
                    err(f"seed {table}.{col} row {rows}: invalid JSON -> {raw[:80]}")
        i += 1
        while i < len(sql) and sql[i] in " \r\n\t":
            i += 1
        if i < len(sql) and sql[i] == ",":
            i += 1
            continue
        break
    table_counts[table] = rows
    pos = i

for t, minimum in {
    "sys_user": 3, "category": 2, "product": 8, "order_info": 6,
    "order_item": 6, "logistics": 3, "refund_request": 2,
    "knowledge_document": 4, "knowledge_chunk": 4, "approval_task": 2,
}.items():
    if table_counts.get(t, 0) < minimum:
        err(f"seed table {t}: {table_counts.get(t, 0)} rows, expected >= {minimum}")
ok(f"seed rows: {table_counts}")

# any string literal that looks like JSON must parse
for m in re.finditer(r"'(?:\{|\[)", sql):
    j = m.start() + 1
    depth, inq, i = 0, False, j
    while i < len(sql):
        c = sql[i]
        if inq:
            if c == "'":
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    i += 1
                else:
                    inq = False
        else:
            if c == "'":
                inq = True
            elif c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
                if depth == 0:
                    break
        i += 1
    raw = sql[j:i + 1].replace("''", "'")
    try:
        json.loads(raw)
    except Exception:
        err(f"seed JSON literal around offset {j} invalid: {raw[:90]}")
ok("seed JSON literals scanned")

# bcrypt hashes must be 60 chars
for h in re.findall(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", sql):
    if len(h) != 60:
        err(f"bcrypt hash length {len(h)}: {h}")
if sql.count("$2a$12$") != 3:
    err(f"expected 3 bcrypt hashes, found {sql.count('$2a$12$')}")

# ---------------------------------------------------------------------------
# 3. bash script structure (no shell available)
# ---------------------------------------------------------------------------
for f in ("deploy/scripts/up.sh", "deploy/scripts/down.sh", "deploy/scripts/logs.sh", "deploy/scripts/reset.sh"):
    p = ROOT / f
    t = p.read_text(encoding="utf-8")
    if not t.startswith("#!/usr/bin/env bash"):
        err(f"{f}: missing bash shebang")
    if t.count("'") % 2 != 0:
        err(f"{f}: odd single quotes")
    if t.count('"') % 2 != 0:
        err(f"{f}: odd double quotes")
    for opener, closer in (("if ", "fi"), ("for ", "done"), ("while ", "done")):
        pass
    if t.count("if ") and t.count("fi") < t.count("if ") - t.count("elif"):
        err(f"{f}: if/fi imbalance (if={t.count('if ')} fi={t.count('fi')})")
    if "docker compose" not in t and f.endswith(("up.sh", "down.sh", "logs.sh", "reset.sh")):
        err(f"{f}: no docker compose call")

# ---------------------------------------------------------------------------
print("ERRORS:")
for e in errors:
    print("  -", e)
print(f"total errors: {len(errors)}")
print("NOTES:")
for n in notes:
    print("  *", n)
sys.exit(1 if errors else 0)
