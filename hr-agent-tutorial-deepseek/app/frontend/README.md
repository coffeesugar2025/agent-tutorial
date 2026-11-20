# HR Agent 学堂 · 前端

Vue 3 `<script setup>` + Vue Router 4 + Vite 6。课程站、HR Agent 工作台与评测看板共用一个单页应用。

## 页面

| 路由 | 说明 |
| --- | --- |
| `/` | 课程首页：hero、技术栈徽章、五段式学习路径、18 章卡片、本地学习进度 |
| `/learn/:slug` | 章节阅读：按 part 分组目录（移动端抽屉）、Markdown、本页 TOC、阅读进度条、上一章/下一章、标记完成 |
| `/playground` | 工作台：身份切换、聊天、执行轨迹、引用来源、记忆、待审批、重置演示数据 |
| `/eval` | 评测看板：5 个指标卡、baseline 对比、20 条用例、Bad Case |
| 其它 | 404 |

## 开发

```powershell
pnpm install
pnpm dev          # 5173，/api 代理到 http://127.0.0.1:8000
```

后端未启动时页面会显示可重试的错误态，不会白屏。

## 构建

```powershell
pnpm build        # 产物输出到 dist/
```

`dist/` 由 FastAPI 静态托管（后端需把非 `/api` 路径回退到 `index.html`）。

构建使用 Vite 标准流程（esbuild 压缩）。如果 `dist/` 已存在，直接启动后端即可，不必每次重新构建。

## API 对接

同源请求 `/api`，严格按 `docs/_APP_API.md`：

- `GET /api/course`、`GET /api/docs/{slug}`、`GET /api/scenarios`
- `POST /api/chat`（`session_id` 由前端生成，`employee_id` 表示演示身份）
- `POST /api/approvals/{id}`（`decision: approve | reject`）
- `POST /api/eval/run`（无请求体）
- `POST /api/demo/reset`（重置演示数据；失败会显示提示并支持重试）

所有请求都有超时与统一错误归一化（`src/api.js`）。

## 本地存储

- `hr-agent-progress-v1`：已完成章节 slug 数组
- `hr-agent-last-chapter`：最近阅读的章节 slug

## 安全与渲染

- 聊天用户内容使用文本插值；Agent 回复先转义原始 HTML，再经 marked 渲染。
- 所有 Markdown 输出都经过 DOM 白名单清洗（移除脚本、事件属性、`javascript:` 链接），再增强标题锚点、代码高亮/复制、callout、表格与 `<details>`。
- 教程约定的四类提示块映射为不同颜色的 callout：小白提示 / 生产提醒 / 动手 / 考点。

## 设计

浅色主题，主色 `#4f46e5`、背景 `#f7f7fb`、正文 `#1f2430`；圆角 12–16px；系统字体栈；正文 16px / 行高 1.8；桌面三栏、移动端单栏 + 抽屉；图标全部为内联 SVG。
