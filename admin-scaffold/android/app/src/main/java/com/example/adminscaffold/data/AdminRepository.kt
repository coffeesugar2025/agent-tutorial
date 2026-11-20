package com.example.adminscaffold.data

import com.example.adminscaffold.core.ApiException
import com.example.adminscaffold.core.ApiResponse
import com.example.adminscaffold.core.TokenStore
import org.json.JSONObject
import retrofit2.HttpException
import java.io.IOException

/**
 * 统一解包 {code,message,data}：code != 0 或非 2xx 一律抛 ApiException，
 * UI 层只需要 runCatching 就能拿到可读错误。
 */
class AdminRepository(
    private val api: AdminApi,
    private val tokenStore: TokenStore
) {
    private suspend fun <T> exec(block: suspend () -> ApiResponse<T>): T? {
        val response = try {
            block()
        } catch (e: HttpException) {
            val raw = e.response()?.errorBody()?.string()
            val message = raw?.let {
                runCatching { JSONObject(it).optString("message") }.getOrNull()
            }?.takeIf { it.isNotBlank() } ?: "请求失败 (HTTP ${e.code()})"
            if (e.code() == 401) tokenStore.clear()
            throw ApiException(e.code(), message)
        } catch (e: IOException) {
            throw ApiException(-1, "网络异常，请检查后端地址与网络：${e.localizedMessage}")
        }

        if (response.code != 0) {
            if (response.code == 401) tokenStore.clear()
            throw ApiException(response.code, response.message ?: "请求失败")
        }
        return response.data
    }

    // 认证
    suspend fun login(username: String, password: String): TokenDto =
        exec { api.login(mapOf("username" to username, "password" to password)) }
            ?: throw ApiException(-1, "登录响应为空")

    suspend fun logout() {
        exec { api.logout() }
    }

    suspend fun me(): Profile =
        exec { api.me() } ?: throw ApiException(-1, "用户信息为空")

    suspend fun menus(): List<Menu> = exec { api.menus() } ?: emptyList()

    // 用户
    suspend fun users(page: Int, size: Int, keyword: String): Page<UserItem> =
        exec { api.users(page, size, keyword) } ?: Page()

    suspend fun createUser(body: JsonBody) {
        exec { api.createUser(body) }
    }

    suspend fun updateUser(id: Int, body: JsonBody) {
        exec { api.updateUser(id, body) }
    }

    suspend fun resetPassword(id: Int, password: String) {
        exec { api.resetPassword(id, mapOf("password" to password)) }
    }

    suspend fun deleteUser(id: Int) {
        exec { api.deleteUser(id) }
    }

    // 角色
    suspend fun roles(page: Int, size: Int, keyword: String): Page<RoleItem> =
        exec { api.roles(page, size, keyword) } ?: Page()

    suspend fun roleOptions(): List<RoleOption> = exec { api.roleOptions() } ?: emptyList()

    suspend fun createRole(body: JsonBody) {
        exec { api.createRole(body) }
    }

    suspend fun updateRole(id: Int, body: JsonBody) {
        exec { api.updateRole(id, body) }
    }

    suspend fun assignPermissions(id: Int, ids: List<Int>) {
        exec { api.assignPermissions(id, mapOf("permission_ids" to ids)) }
    }

    suspend fun deleteRole(id: Int) {
        exec { api.deleteRole(id) }
    }

    // 权限
    suspend fun permissions(page: Int, size: Int, keyword: String, module: String): Page<PermissionItem> =
        exec { api.permissions(page, size, keyword, module) } ?: Page()

    suspend fun permissionTree(): List<PermGroup> = exec { api.permissionTree() } ?: emptyList()

    suspend fun createPermission(body: JsonBody) {
        exec { api.createPermission(body) }
    }

    suspend fun updatePermission(id: Int, body: JsonBody) {
        exec { api.updatePermission(id, body) }
    }

    suspend fun deletePermission(id: Int) {
        exec { api.deletePermission(id) }
    }

    // 审计 / 运维
    suspend fun auditLogs(
        page: Int,
        size: Int,
        keyword: String,
        action: String
    ): Page<AuditItem> = exec { api.auditLogs(page, size, keyword, action) } ?: Page()

    suspend fun health(): HealthState =
        exec { api.health() } ?: HealthState()
}
