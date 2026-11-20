package com.example.adminscaffold.data

import com.example.adminscaffold.core.ApiResponse
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

interface AdminApi {
    // ---- 认证 ----
    @POST("auth/login")
    suspend fun login(@Body body: JsonBody): ApiResponse<TokenDto>

    @POST("auth/refresh")
    suspend fun refresh(@Body body: JsonBody): ApiResponse<TokenDto>

    @POST("auth/logout")
    suspend fun logout(): ApiResponse<Any>

    @GET("auth/me")
    suspend fun me(): ApiResponse<Profile>

    @GET("auth/menus")
    suspend fun menus(): ApiResponse<List<Menu>>

    // ---- 用户 ----
    @GET("users")
    suspend fun users(
        @Query("page") page: Int,
        @Query("size") size: Int,
        @Query("keyword") keyword: String
    ): ApiResponse<Page<UserItem>>

    @POST("users")
    suspend fun createUser(@Body body: JsonBody): ApiResponse<UserItem>

    @PUT("users/{id}")
    suspend fun updateUser(@Path("id") id: Int, @Body body: JsonBody): ApiResponse<UserItem>

    @PATCH("users/{id}/reset-password")
    suspend fun resetPassword(@Path("id") id: Int, @Body body: JsonBody): ApiResponse<Any>

    @DELETE("users/{id}")
    suspend fun deleteUser(@Path("id") id: Int): ApiResponse<Any>

    // ---- 角色 ----
    @GET("roles")
    suspend fun roles(
        @Query("page") page: Int,
        @Query("size") size: Int,
        @Query("keyword") keyword: String
    ): ApiResponse<Page<RoleItem>>

    @GET("roles/options")
    suspend fun roleOptions(): ApiResponse<List<RoleOption>>

    @POST("roles")
    suspend fun createRole(@Body body: JsonBody): ApiResponse<RoleItem>

    @PUT("roles/{id}")
    suspend fun updateRole(@Path("id") id: Int, @Body body: JsonBody): ApiResponse<RoleItem>

    @PUT("roles/{id}/permissions")
    suspend fun assignPermissions(@Path("id") id: Int, @Body body: JsonBody): ApiResponse<RoleItem>

    @DELETE("roles/{id}")
    suspend fun deleteRole(@Path("id") id: Int): ApiResponse<Any>

    // ---- 权限 ----
    @GET("permissions")
    suspend fun permissions(
        @Query("page") page: Int,
        @Query("size") size: Int,
        @Query("keyword") keyword: String,
        @Query("module") module: String
    ): ApiResponse<Page<PermissionItem>>

    @GET("permissions/tree")
    suspend fun permissionTree(): ApiResponse<List<PermGroup>>

    @POST("permissions")
    suspend fun createPermission(@Body body: JsonBody): ApiResponse<PermissionItem>

    @PUT("permissions/{id}")
    suspend fun updatePermission(
        @Path("id") id: Int,
        @Body body: JsonBody
    ): ApiResponse<PermissionItem>

    @DELETE("permissions/{id}")
    suspend fun deletePermission(@Path("id") id: Int): ApiResponse<Any>

    // ---- 审计 / 运维 ----
    @GET("audit-logs")
    suspend fun auditLogs(
        @Query("page") page: Int,
        @Query("size") size: Int,
        @Query("keyword") keyword: String,
        @Query("action") action: String
    ): ApiResponse<Page<AuditItem>>

    @GET("health")
    suspend fun health(): ApiResponse<HealthState>
}
