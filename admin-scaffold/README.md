# FastAPI + Vue3 + Android 管理系统脚手架

Python 3.12 / FastAPI 后端，Vue 3 + Vite + TypeScript + Element Plus 网页端，Kotlin + Jetpack Compose 安卓端，统一封装 MySQL、Redis、RabbitMQ、Kafka、Elasticsearch，内置登录认证、RBAC 权限管理、用户/角色/权限/审计日志的完整增删改查。三端共用同一套 `/api/v1` 接口。

## 目录结构

```
admin-scaffold/
├── docker-compose.yml          # 一键启动 5 个中间件 + 前后端
├── backend/
│   ├── requirements.txt        # 默认（asyncmy 0.2.10）
│   ├── requirements-nocompile.txt  # 免编译备选（aiomysql）
│   ├── .env.example            # 本地开发配置模板
│   ├── Dockerfile
│   ├── main.py                 # 兼容入口：uvicorn main:app 也能用
│   ├── app/
│   │   ├── main.py             # 应用入口、lifespan、全局异常处理
│   │   ├── core/               # 配置 / JWT+bcrypt / 依赖注入与权限校验
│   │   ├── db/                 # mysql(async SQLAlchemy) / redis / elasticsearch
│   │   ├── mq/                 # rabbitmq / kafka
│   │   ├── models.py           # User / Role / Permission + 关联表
│   │   ├── schemas.py          # Pydantic 模型与统一响应结构
│   │   ├── crud.py             # 泛型分页 CRUD
│   │   ├── services/           # 认证服务 / 审计事件分发
│   │   └── api/                # auth / users / roles / permissions / audit / health
│   └── scripts/seed.py         # 幂等初始化权限、角色、管理员
└── frontend/
    ├── src/
    │   ├── api/                # axios 封装 + 全部接口
    │   ├── router/ stores/     # 路由守卫 + Pinia 用户态
    │   ├── directives/         # v-permission 按钮级权限
    │   ├── layout/             # 侧边菜单 + 顶栏
    │   └── views/              # 登录、工作台、用户、角色、权限、审计日志
    ├── Dockerfile / nginx.conf
    └── vite.config.ts          # /api 代理到后端
├── android/                    # Kotlin + Compose 客户端（Android Studio 打开）
│   ├── gradle/libs.versions.toml
│   ├── app/build.gradle.kts    # API_BASE_URL 配置
│   ├── app/src/main/java/com/example/adminscaffold/
│   │   ├── core/               # DI 容器、TokenStore、拦截器、分页 VM 基类
│   │   ├── data/               # Models / Retrofit 接口 / 仓库层
│   │   └── ui/                 # 登录、抽屉主框架、四个 CRUD 页、审计日志
│   └── README.md
└── README.md
```

## 快速开始（推荐）

```bash
cd admin-scaffold
docker compose up -d --build
```

- 网页前端：http://localhost:8080
- 后端接口文档：http://localhost:8000/docs
- RabbitMQ 控制台：http://localhost:15672 （guest / guest）
- 健康检查：`GET http://localhost:8000/api/v1/health`
- 安卓端：用 Android Studio 打开 `android/`，模拟器默认连 `http://10.0.2.2:8000/api/v1/`，详见 `android/README.md`（compose 不构建安卓，需单独运行）

默认账号：`admin` / `Admin@123`（首次启动由 `seed.py` 创建，**上线前务必修改**）。

## 本地开发

```bash
# 1. 只起中间件（MySQL 必须先起，否则后端启动会失败）
docker compose up -d mysql redis rabbitmq kafka elasticsearch

# 2. 后端：务必 cd 到 backend/ 目录
cd backend
cp .env.example .env
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. 前端
cd ../frontend
npm install
npm run dev          # http://localhost:5173，/api 代理到 8000
```

MySQL 是唯一强依赖；Redis / RabbitMQ / Kafka / ES 连不上时会自动降级并在日志告警，登录和 CRUD 依然可用，可通过 `/api/v1/health` 查看各组件连通状态。

### 启动报错 `Could not import module "main"`

**原因**：后端是包结构，FastAPI 实例在 `backend/app/main.py`，不是 `backend/main.py`。执行 `uvicorn main:app` 时 uvicorn 会在当前目录找顶层 `main` 模块，找不到就报这个错——注意它发生在 **import 阶段**，跟数据库、依赖装没装全都没关系。

**正确命令**（两种等价，都必须在 `backend/` 目录下执行）：

```bash
uvicorn app.main:app --reload --port 8000   # 规范写法
uvicorn main:app --reload --port 8000       # 兼容写法，backend/main.py 已做转发
```

不要写成 `uvicorn app/main.py:app`、也不要在 `admin-scaffold/` 根目录执行 `uvicorn backend.app.main:app`（那样 `scripts.seed` 会找不到）。

**改对命令后还起不来，按这两步查**：

```bash
# ① 先单独验证 import 链，能打印标题说明所有依赖都装好了
python -c "from app.main import app; print(app.title)"
# 若报 ModuleNotFoundError: No module named 'xxx' → 缺哪个装哪个，或重跑 pip install -r requirements.txt

# ② 确认 MySQL 已监听 3306（Windows PowerShell）
Test-NetConnection 127.0.0.1 -Port 3306
```

若日志出现 `[mysql] 初始化失败：...`，说明连不上 MySQL：先 `docker compose up -d mysql`，再核对 `backend/.env` 里的 `MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB / MYSQL_DRIVER`。MySQL 连不上时服务会明确失败退出，这是预期行为，不是可选降级组件。

### Windows / Python 3.12 安装依赖报错（asyncmy 编译失败）

**现象**：`pip install -r requirements.txt` 卡在 `Failed building wheel for asyncmy` / `setup.py build` 返回 1。

**根因**：`asyncmy` 是 Cython 写的 C 扩展，Windows 上没有对应 wheel 时 pip 会退化为源码编译，需要 MSVC Build Tools + Cython；而 `asyncmy 0.2.9` 恰恰没有 `cp312` 的 wheel（0.2.10 才补上 Python 3.12 的预编译文件）[citation:2][citation:1]。本机若没装 VS C++ 生成工具，编译必然失败。

**方案 A（默认，脚手架已改好）**：把 `asyncmy` 升到 `0.2.10`，它提供 `cp312-win_amd64` 预编译 wheel，直接下载安装、不编译 [citation:14][citation:15]。本地修复命令：

```bash
python -m pip install -U pip setuptools wheel
pip install --only-binary=:all: asyncmy==0.2.10   # 强制只装 wheel，能装上就说明命中预编译包
pip install -r requirements.txt
```

若国内镜像还没同步 0.2.10 的 wheel，临时指定官方源：`pip install --only-binary=:all: -i https://pypi.org/simple asyncmy==0.2.10`。

**方案 B（永久免编译，推荐给不想装 VS 的机器）**：换成 `aiomysql` 纯 Python 驱动，SQLAlchemy 2.0 官方支持 `mysql+aiomysql` 方言 [citation:17][citation:20]，全平台零编译：

```bash
pip install -r requirements-nocompile.txt
# .env 里加一行
MYSQL_DRIVER=aiomysql
```

`app/core/config.py` 的 `mysql_url` 会按 `MYSQL_DRIVER` 生成连接串，业务代码一行都不用改。两个 requirements 文件**二选一**，不要同时装。性能上 asyncmy 略快，但管理系统的 CRUD 量级感知不到差异。

### 启动报错 `'cryptography' package is required for caching_sha2_password`

**现象**：import 和端口都通了，服务却在启动时连库失败，堆栈末尾是

```
RuntimeError: 'cryptography' package is required for sha256_password or caching_sha2_password auth methods
```

**根因**：MySQL 8.0 默认认证插件是 `caching_sha2_password`，非缓存命中路径需要用 RSA 加密传输密码；`asyncmy`（以及 `aiomysql` / `PyMySQL`）都把这一步交给 `cryptography` 库，而它属于**可选依赖**，不会随驱动自动装上 [citation:7][citation:10][citation:11]。`docker-compose.yml` 里的 `mysql:8.0` 同样是默认该插件，所以本地用 compose 起库必然遇到。

**修复（一条命令）**：

```bash
pip install cryptography
# 或重跑完整依赖，脚手架已把 cryptography 写进两个 requirements 文件
pip install -r requirements.txt
```

`cryptography` 有 Windows / Linux / macOS 的预编译 wheel，秒装、不需要编译器。装完重启 `uvicorn` 即可。若随后变成 `Access denied for user ...`，说明认证链路已通、只是密码不对，核对 `.env` 的 `MYSQL_USER / MYSQL_PASSWORD`（compose 默认是 `admin / admin123`）。

> 不推荐的规避方式：把用户改成 `mysql_native_password`（`ALTER USER ... IDENTIFIED WITH mysql_native_password BY '...'`）。它降低了认证强度，且 MySQL 8.4+ 已默认移除该插件；装一个依赖就能解决，没必要动服务端。

### 启动报错 `LoaderStrategyException: Can't find strategy (('lazy', 'selectinload'),)`

**现象**：依赖和数据库都通了，第一次查询时 mapper 初始化失败，堆栈末端是上面这条。

**根因**：`relationship()` 的 `lazy` 参数合法值只有 `select` / `joined` / `selectin` / `subquery` / `raise` / `noload` 等；`selectinload` 是**查询期** `options(selectinload(...))` 的加载器名，两者同名不同物 [citation:4][citation:5]。脚手架早期版本在 `models.py` 里误写了 `lazy="selectinload"`，SQLAlchemy 在执行第一条 SELECT 编译 mapper 时找不到对应策略就抛异常。

**修复**：`backend/app/models.py` 里 4 处全部改成 `lazy="selectin"`：

```powershell
# 在 backend/ 目录执行（或编辑器里 Ctrl+H 全局替换，更直观）
(Get-Content app\models.py -Encoding UTF8) -replace 'lazy="selectinload"', 'lazy="selectin"' | Set-Content app\models.py -Encoding UTF8
```

`selectin` 会在加载主对象后自动发一条 `IN` 查询把关联集合填好，正好避开异步 SQLAlchemy 里访问未加载关系会触发 `MissingGreenlet` 的问题；`deps.py` / `crud.py` 里的 `options(selectinload(...))` 写法本身是合法的，不用动。

已用真实 SQLAlchemy 2.0.36 复现（旧值精确抛出该异常）并验证：`configure_mappers()`、链式 `selectinload(User.roles).selectinload(Role.permissions)`、不带 options 的自动加载、删除角色时维护关联表，四项全部通过。**表结构没变，不需要删库重建**，改完重启服务即可，`seed.py` 是幂等的，会自动补齐权限、角色和初始管理员。

### 启动报错 `MissingGreenlet: greenlet_spawn has not been called`

**现象**：认证和建表都过了，`seed()` 阶段抛

```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here.
[SQL: SELECT ... FROM sys_permission, sys_role_permissions WHERE %s = sys_role_permissions.role_id ...]
```

**根因**：异步 SQLAlchemy 的所有 IO 必须发生在 `await db.execute(...)` 的 greenlet 上下文里。一旦在普通代码里访问**未加载的 ORM 关系**，SQLAlchemy 会尝试发一条同步 lazy load，但此时没有 greenlet 可用，就抛这个错（SQLAlchemy 官方 Error Messages 文档把它归为「在意外位置尝试了 IO」）。注意报错 SQL 是按**单个 `role_id`** 查关联表——这正是 lazy load 的特征，不是批量 `IN`。

脚手架早期版本有两个触发点：

1. `seed.py` 先 `db.add(Role(...))` + `flush()`，再执行 `role.permissions = list(all_perms)`。新建对象变成 persistent 后集合未加载，ORM 为计算增删差集先去 lazy load 旧值 → 隐式 IO。
2. `crud.py` 的 `get()` / `delete()` 用 `session.get()`，它**不应用** mapper 级 `selectin` 预加载；后续 `user.roles = ...`、`role.permissions = ...` 以及删除父对象时清理关联表，都会触发隐式 IO。所以即使跳过 seed，编辑用户、分配权限、删除接口在独立请求里同样会炸。

**修复（脚手架已全部改好）**：

| 位置 | 改动 |
|---|---|
| `scripts/seed.py` | 新建 `Role` / `User` 时把关联集合直接传进构造函数（`permissions=...` / `roles=[role]`），不在 flush 后赋值；已存在的对象由 `selectinload` 预加载后再赋值 |
| `app/crud.py` | `CRUDBase` 支持 `eager_options` / `delete_options`；`get()`、`list()`、`delete()` 一律走 `select(...).options(selectinload(...))`，不再用 `session.get()` |
| 各 CRUD 实例 | `user_crud` 预加载 `User.roles`；`role_crud` 预加载 `Role.permissions`，删除时额外加载 `Role.users`；`permission_crud` 删除时加载 `Permission.roles` |

`deps.py` / `services/auth.py` 里的链式 `selectinload(User.roles).selectinload(Role.permissions)` 本来就是正确写法，保持不变。

验证方式：用 SQLAlchemy 2.0.36 + aiosqlite 真实跑通 `seed()` 两次（幂等）、用户/角色/权限的 `get / list / create / update / delete`、全新会话下模拟独立请求的编辑与删除、以及 `/auth/me` 的链式预加载，全部通过。**表结构未变，不用删库**，替换文件后重启即可。

> 排查同类问题的通用原则：异步会话里**永远不要依赖隐式 lazy load**。要么在查询时显式 `options(selectinload(...))`，要么把模型关系设为 `lazy="raise_on_sql"` 让漏网之鱼立刻报出清晰错误。

Kafka 采用官方 `apache/kafka:3.7.1` KRaft 单节点与双 listener：宿主机本地开发用 `localhost:9092`（`.env.example` 默认值），compose 内的 backend 走 `kafka:29092`，避免广播地址指向容器内 localhost 导致连不上。

## 接口清单

| 模块 | 方法与路径 | 权限码 |
|---|---|---|
| 认证 | POST `/api/v1/auth/login` / `refresh` / `logout` | 公开 |
| 认证 | GET `/api/v1/auth/me` / `menus` | 登录 |
| 用户 | GET/POST `/api/v1/users` | `user:list` / `user:create` |
| 用户 | PUT/DELETE `/api/v1/users/{id}` | `user:update` / `user:delete` |
| 用户 | PATCH `/api/v1/users/{id}/reset-password` | `user:update` |
| 角色 | GET/POST `/api/v1/roles`，PUT/DELETE `/api/v1/roles/{id}` | `role:list/create/update/delete` |
| 角色 | PUT `/api/v1/roles/{id}/permissions`、GET `/api/v1/roles/options` | `role:update` / 登录 |
| 权限 | GET/POST `/api/v1/permissions`，PUT/DELETE `/api/v1/permissions/{id}` | `permission:list/create/update/delete` |
| 权限 | GET `/api/v1/permissions/tree` | 登录 |
| 审计 | GET `/api/v1/audit-logs?keyword=&action=&page=&size=` | `audit:list` |
| 运维 | GET `/api/v1/health` | 公开 |

统一响应：`{"code": 0, "message": "ok", "data": ...}`；分页 data 为 `{"items": [], "total": n, "page": 1, "size": 20}`。失败时 `code` 为 HTTP 状态码。

## 关键设计

- **认证**：JWT access + refresh；Redis 保存 refresh jti、access 退出黑名单；bcrypt 哈希密码。
- **权限**：User → Role → Permission 三级；后端 `Depends(require_perm("user:create"))` 接口级拦截，Vue3 菜单按 `/auth/menus` 过滤 + `v-permission` 按钮级控制，Android 抽屉按 `/auth/menus` 渲染 + `Perms(code)` 控制按钮显隐；`super_admin` 直通。三端权限码完全对齐。
- **审计**：所有写操作经 `services/audit.py` 异步分发三路 —— ES 索引（检索）、RabbitMQ topic 交换（`audit.*`）、Kafka topic（`admin.audit`），各带示例消费者；任一失败只记日志不阻断业务。
- **MySQL**：SQLAlchemy 2.0 async + asyncmy，异步会话、连接池、统一分页 CRUD；启动 `create_all` + 幂等 seed，生产请接 Alembic。
- **降级**：所有可选中间件在 lifespan 里惰性探测，`.env` 中 `ENABLE_*` 可单独关闭。

## 上线前必做

1. 修改 `SECRET_KEY`、`INIT_ADMIN_PASSWORD`、MySQL/Redis/RabbitMQ 密码，开启 ES 鉴权与 TLS。
2. 用 Alembic 管理表结构变更，关闭 `DEBUG` 与 `echo` SQL 日志。
3. 网页路由守卫、按钮指令与安卓端菜单/按钮显隐都只是体验层，真实安全边界始终在后端 `require_perm`。
4. 审计日志消费者按业务需要落库或转数仓，避免示例里仅打印日志。
5. 安卓 release 包必须把 `API_BASE_URL` 换成 HTTPS 域名、收紧 `network_security_config.xml` 的明文放行，并把 token 改存加密存储。
