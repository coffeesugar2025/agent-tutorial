# 电商智能体控制台 · 前端

Vue 3 + Vite + TypeScript + Element Plus 的单页控制台，一套代码同时对接 **Python（FastAPI）** 与 **Java（Spring Boot）** 两套后端。所有接口遵循 `docs/03-API契约.md` 的统一响应信封。

## 环境要求

- Node.js >= 18.18（推荐 20 LTS）
- npm >= 9

> 仓库未提交 lockfile，`npm install` 会解析依赖；生产构建可用 `npm ci`（存在 lockfile 时）。

## 开发 / 构建

```bash
cd frontend
npm install

npm run dev          # Vite dev server，默认 http://localhost:5173
npm run type-check   # vue-tsc --noEmit，仅类型检查
npm run build        # vue-tsc 类型检查 + vite build，产物在 dist/
npm run preview      # 预览 dist/，默认 http://localhost:8088

npm test             # vitest（tests/**/*.spec.ts；当前仓库尚未提供用例目录）
```

`npm run dev` 默认把 `/api` 与 `/health` 代理到 `VITE_PROXY_TARGET`（默认 `http://localhost:8000`）。想直连后端也可以把 `VITE_API_BASE` 改成完整地址，但需要后端开启 CORS。

## 切换 Python / Java 后端

有两种方式，互不冲突：

### 1. 构建期：`.env`

复制 `.env.example` 为 `.env.local`（或直接改 `.env.development`）：

```dotenv
VITE_API_BASE=/api/v1                    # 默认基地址；也可写 http://localhost:8000/api/v1
VITE_PROXY_TARGET=http://localhost:8000  # 仅 dev server 的 /api 代理目标
VITE_BACKEND_PYTHON=http://localhost:8000/api/v1
VITE_BACKEND_JAVA=http://localhost:8080/api/v1
```

- `VITE_API_BASE` 是 axios 的默认基地址，优先级最低。
- `VITE_BACKEND_PYTHON` / `VITE_BACKEND_JAVA` 决定「设置」页与顶栏切换器里的两个预设。
- 修改 `.env` 后需要重启 dev server；构建产物需要重新 `npm run build`。

### 2. 运行期：设置页 / 顶栏切换器

- 顶栏右侧的 **后端切换器** 与「设置」页的「后端连接」卡片是同一份状态。
- 切换会把选择写入 `localStorage`（`ecom.api.backend` / `ecom.api.base`），axios 请求拦截器即时读取，无需刷新实例。
- Token 与用户信息按 **API 基地址** 隔离存储，切到另一套后端后需要重新登录；切换时页面会自动跳转登录并整页刷新以清空各页面缓存。
- 选择「自定义后端…」可填写任意基地址（必须包含 `/api/v1` 前缀）。

### 兜底顺序

`localStorage 中的基地址` → `VITE_API_BASE` → `/api`（见 `src/api/http.ts` 的 `getApiBase()`）。

## 目录说明

```
frontend/
├── index.html
├── vite.config.ts          # @ 别名、/api 与 /health 代理、分包
├── Dockerfile              # 多阶段构建：node 构建 → nginx 运行（8088）
├── nginx.conf              # SPA history 回退；/api 反代并关闭缓冲（SSE 必需）
├── .env.example / .env.development
└── src/
    ├── main.ts             # 应用入口：Pinia、Router、Element Plus（zh-CN）
    ├── App.vue             # 根组件，仅 <router-view />
    ├── router/index.ts     # 路由、登录守卫、ADMIN 角色守卫、401 回调
    ├── layouts/DefaultLayout.vue   # 侧边栏 + 顶栏 + 内容区
    ├── views/              # 页面级组件（见下表）
    ├── components/
    │   ├── common/         # PageHeader / MetricCard / DataState / EmptyState / BackendSwitcher
    │   ├── chart/          # ECharts 封装：LineChart / BarChart / PieChart / useChart
    │   ├── chat/           # 对话流、Agent 徽标、工具调用、审批卡片等
    │   ├── knowledge/      # 文档上传、索引任务、检索调试
    │   ├── observability/  # 概览 / Trace 列表与抽屉 / Span 时间线 / 成本 / 模型健康
    │   ├── product/ order/ # 商品详情、订单详情、物流时间线
    │   └── ...
    ├── api/                # http 封装（信封解包、401、后端切换）+ 各领域接口
    ├── stores/             # Pinia：auth（登录态）、ui（后端/能力/侧边栏）、chat（会话）
    ├── types/              # 与 API 契约一一对应的 TS 类型，统一从 '@/types' 导出
    ├── utils/              # 格式化、类型守卫、SSE 解析、存储
    └── styles/             # SCSS 变量 + 全局工具类（.page/.panel/.toolbar/.stat-grid 等）
```

### 页面与权限

| 路由 | 页面 | 说明 | 角色 |
| --- | --- | --- | --- |
| `/chat` | `ChatView.vue` | SSE 流式对话、工具调用、审批 | 登录用户 |
| `/products` | `ProductsView.vue` | 商品检索 + 详情抽屉 | 登录用户 |
| `/orders` | `OrdersView.vue` | 订单列表 + 物流时间线 | 登录用户 |
| `/knowledge` | `KnowledgeView.vue` | 文档管理、索引任务、检索调试 | ADMIN / OPS |
| `/observability` | `ObservabilityView.vue` | 运营指标、Trace 链路、成本、模型健康 | ADMIN |
| `/evals` | `EvalView.vue` | 触发评测、轮询 pass rate / pass^k、用例结果 | ADMIN |
| `/settings` | `SettingsView.vue` | 后端切换、能力探测、依赖健康、构建期配置 | 登录用户 |
| `/login` | `LoginView.vue` | 登录（公开） | — |

角色守卫在 `router/index.ts` 的 `beforeEach` 中执行，无权限会提示并重定向到 `/chat`。

## 开发约定

- 页面统一使用 `PageHeader` + `.panel` / `.toolbar` / `.stat-grid` 等全局工具类，风格参考 `views/ProductsView.vue`。
- 请求一律走 `src/api/*`，不要直接 `axios`；`api/http.ts` 已统一解包信封、处理超时与 401。
- 列表/详情的数据态统一交给 `DataState`（loading / error / empty + retry），指标卡用 `MetricCard`，图表用 `components/chart/*`。
- API 类型只从 `@/types` 导入；组件内不重复定义接口类型。
- 可观测与评测的数据都来自 `/admin/*`（ADMIN 权限），后端 `GET /health` 位于 `/api/v1` 前缀之外，`api/admin.ts` 已单独处理。

## 部署

```bash
docker build -t ecom-console ./frontend
docker run --rm -p 8088:8088 ecom-console
```

- 构建期可通过 `--build-arg VITE_API_BASE=...` 注入基地址（Dockerfile 默认 `/api/v1`）。
- `nginx.conf` 将 `/api/` 反代到 `http://backend-python:8000`，并关闭 `proxy_buffering` 保证 SSE 不被攒包；部署 Java 后端时把 `proxy_pass` 改为对应服务即可。
- 若前后端不同源部署，直接在 `.env` 里把 `VITE_API_BASE` 指向完整地址，并确保后端 CORS 放行前端域名。

## 排查

| 现象 | 排查方向 |
| --- | --- |
| 页面顶部提示「能力探测失败」 | 后端未启动、基地址缺少 `/api/v1`、跨域被拦 |
| 登录后切换后端又被踢回登录 | 预期行为：Token 按基地址隔离，需在新后端重新登录 |
| 对话没有流式输出 | 反向代理开启了缓冲；确认 SSE 相关响应头与 `proxy_buffering off` |
| `/health` 失败但接口正常 | `getHealth()` 请求的是站点根 `/health`，不是 `/api/v1/health` |
