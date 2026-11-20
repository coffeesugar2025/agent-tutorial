# Android 客户端（Compose 版）

与 Vue3 前端对齐全套业务：登录/退出、动态菜单、按钮级权限、工作台、用户/角色/权限 CRUD、角色分配权限、重置密码、审计日志检索。直接调用同一套 `/api/v1` 后端接口，无需改动服务端。

## 技术栈

| 项 | 选型 |
|---|---|
| 语言 | Kotlin 2.0.21（JDK 17） |
| UI | Jetpack Compose + Material3（Compose BOM 2024.12.01） |
| 网络 | Retrofit 2.11 + OkHttp 4.12 + Gson |
| 状态 | ViewModel + StateFlow + `collectAsStateWithLifecycle` |
| 导航 | Navigation Compose 2.8.5（抽屉菜单） |
| 本地存储 | SharedPreferences 保存 access token |
| 构建 | AGP 8.7.3 / Gradle 8.9 / Version Catalog |

## 目录结构

```
android/
├── settings.gradle.kts / build.gradle.kts
├── gradle/libs.versions.toml          # 所有依赖版本集中管理
├── gradle/wrapper/gradle-wrapper.properties
└── app/src/main/
    ├── AndroidManifest.xml
    ├── res/xml/network_security_config.xml   # 仅允许本地地址 HTTP 明文
    └── java/com/example/adminscaffold/
        ├── AdminApp.kt / MainActivity.kt
        ├── core/        # AppContainer 手动 DI、TokenStore、拦截器、分页 VM 基类
        ├── data/        # Models、AdminApi(Retrofit)、AdminRepository(统一解包)
        └── ui/
            ├── AppRoot.kt / Routes.kt / theme/
            ├── common/    # 搜索栏、分页条、加载条、确认框、表单字段、Snackbar 错误处理
            ├── auth/      # 登录
            ├── main/      # 抽屉导航 + 顶栏 + NavHost
            ├── dashboard/ # 用户信息 + 中间件连通状态
            ├── users/     # 列表/新增/编辑/删除/重置密码/角色多选
            ├── roles/     # 列表/CRUD/权限树勾选分配
            ├── permissions/ # 列表/CRUD/模块筛选
            └── audit/     # ES 审计日志检索与动作筛选
```

## 运行

1. 先启动后端：`cd .. && docker compose up -d`（或本地 `uvicorn app.main:app --host 0.0.0.0 --port 8000`）。
2. 用 **Android Studio（Ladybug / 2024.2 及以上）** 打开 `android/` 目录，等待 Gradle Sync 完成。
3. 模拟器直接运行即可：默认 `API_BASE_URL = http://10.0.2.2:8000/api/v1/`（`app/build.gradle.kts`），`10.0.2.2` 是模拟器访问宿主机的专用地址。
4. 默认账号 `admin` / `Admin@123`。

**真机调试**：把 `buildConfigField` 改成电脑局域网 IP（如 `http://192.168.1.20:8000/api/v1/`），并在 `res/xml/network_security_config.xml` 的 `<domain-config>` 里加上同一个 IP，否则 Android 9+ 会拦截明文 HTTP。手机与电脑需在同一局域网。

> 仓库里只有 `gradle-wrapper.properties`，未包含 `gradle-wrapper.jar` 二进制文件。用 Android Studio 打开时会自动生成；纯命令行可在项目根目录执行 `gradle wrapper`（需本机已装 Gradle 8.9）。

## 与后端接口的对应关系

| 页面 | 调用接口 |
|---|---|
| 登录 / 退出 | `POST /auth/login`、`POST /auth/logout` |
| 抽屉菜单、按钮显隐 | `GET /auth/me`、`GET /auth/menus` |
| 工作台 | `GET /health` |
| 用户管理 | `GET/POST /users`、`PUT/DELETE /users/{id}`、`PATCH /users/{id}/reset-password`、`GET /roles/options` |
| 角色管理 | `GET/POST /roles`、`PUT/DELETE /roles/{id}`、`PUT /roles/{id}/permissions`、`GET /permissions/tree` |
| 权限管理 | `GET/POST /permissions`、`PUT/DELETE /permissions/{id}` |
| 审计日志 | `GET /audit-logs` |

统一响应 `{code,message,data}` 在 `AdminRepository.exec()` 里解包；`code != 0` 或 HTTP 非 2xx 抛 `ApiException`，UI 用 Snackbar 提示。OkHttp 拦截器自动带 `Authorization: Bearer`，遇到 401 自动清空 token，`AppRoot` 随即切回登录页。

权限口径与 Vue3 一致：`Profile.is_superuser` 直通，否则按 `permissions` 集合判断；后端 `require_perm` 仍是真正的安全边界，客户端控制只影响显隐。

## 已知简化（相对 Vue3 / 生产要求）

- 分页用「上一页/下一页 + 总数」控件，没有页码跳转与每页条数选择。
- 未实现 access token 过期后的 refresh 自动续期（接口已预留 `POST /auth/refresh`），过期后重新登录即可；Vue3 端同样未接自动刷新。
- token 存明文 SharedPreferences，生产请换 `EncryptedSharedPreferences` 或 Android Keystore。
- 无离线缓存、无深色主题完整适配、无单元测试；依赖注入为手动 `AppContainer`，可平滑替换为 Hilt。
- 发布前务必把 `release` 的 `API_BASE_URL` 改成 HTTPS 域名，并收紧 `network_security_config.xml`（删除明文放行）。
