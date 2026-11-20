package com.example.adminscaffold.data

import com.google.gson.annotations.SerializedName

/** 请求体统一用 Map，由 Gson 序列化，避免为每个表单再建 Request 类 */
typealias JsonBody = Map<String, Any>

data class TokenDto(
    @SerializedName("access_token") val accessToken: String = "",
    @SerializedName("refresh_token") val refreshToken: String = "",
    @SerializedName("expires_in") val expiresIn: Int = 0
)

data class Profile(
    val id: Int = 0,
    val username: String = "",
    val nickname: String = "",
    @SerializedName("is_superuser") val isSuperuser: Boolean = false,
    val roles: List<String> = emptyList(),
    val permissions: List<String> = emptyList()
)

data class Menu(
    val path: String = "",
    val title: String = "",
    val icon: String = "",
    val perm: String = ""
)

data class Page<T>(
    val items: List<T> = emptyList(),
    val total: Int = 0,
    val page: Int = 1,
    val size: Int = 20
)

data class UserItem(
    val id: Int = 0,
    val username: String = "",
    val nickname: String = "",
    val email: String = "",
    val phone: String = "",
    @SerializedName("is_active") val isActive: Boolean = true,
    @SerializedName("is_superuser") val isSuperuser: Boolean = false,
    @SerializedName("created_at") val createdAt: String = "",
    val roles: List<String> = emptyList(),
    @SerializedName("role_ids") val roleIds: List<Int> = emptyList()
)

data class RoleOption(
    val id: Int = 0,
    val code: String = "",
    val name: String = ""
)

data class RoleItem(
    val id: Int = 0,
    val code: String = "",
    val name: String = "",
    val description: String = "",
    @SerializedName("is_active") val isActive: Boolean = true,
    @SerializedName("created_at") val createdAt: String = "",
    @SerializedName("permission_ids") val permissionIds: List<Int> = emptyList()
)

data class PermissionItem(
    val id: Int = 0,
    val code: String = "",
    val name: String = "",
    val module: String = "",
    val kind: String = "api",
    val sort: Int = 0,
    @SerializedName("created_at") val createdAt: String = ""
)

data class PermChild(
    val id: Int = 0,
    val code: String = "",
    val name: String = "",
    val kind: String = ""
)

data class PermGroup(
    val module: String = "",
    val children: List<PermChild> = emptyList()
)

data class AuditItem(
    val ts: String = "",
    val username: String = "",
    val action: String = "",
    val resource: String = "",
    val detail: String = "",
    val ip: String = ""
)

data class HealthState(
    val mysql: Boolean = false,
    val redis: Boolean = false,
    val rabbitmq: Boolean = false,
    val kafka: Boolean = false,
    val elasticsearch: Boolean = false
) {
    fun entries(): List<Pair<String, Boolean>> = listOf(
        "MySQL 主库" to mysql,
        "Redis 缓存 / Token" to redis,
        "RabbitMQ 事件" to rabbitmq,
        "Kafka 审计流" to kafka,
        "Elasticsearch 检索" to elasticsearch
    )
}
