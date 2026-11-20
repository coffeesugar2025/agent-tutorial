package com.example.adminscaffold.core

import com.google.gson.annotations.SerializedName
import okhttp3.Interceptor
import okhttp3.Response

/** 后端统一响应：{"code":0,"message":"ok","data":...} */
data class ApiResponse<T>(
    @SerializedName("code") val code: Int = -1,
    @SerializedName("message") val message: String? = null,
    @SerializedName("data") val data: T? = null
)

class ApiException(val code: Int, message: String) : Exception(message)

/** 每次请求自动带 Bearer token */
class AuthInterceptor(private val tokenStore: TokenStore) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val builder = chain.request().newBuilder()
        tokenStore.current()?.takeIf { it.isNotBlank() }?.let {
            builder.header("Authorization", "Bearer $it")
        }
        builder.header("Accept", "application/json")
        return chain.proceed(builder.build())
    }
}

/** 401 统一注销：包含业务层把 code=401 包在 200 响应里的情况 */
class UnauthorizedInterceptor(private val tokenStore: TokenStore) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val response = chain.proceed(chain.request())
        if (response.code == 401) {
            tokenStore.clear()
            return response
        }
        if (response.isSuccessful) {
            val body = runCatching { response.peekBody(4096).string() }.getOrNull().orEmpty()
            if (body.contains("\"code\":401") || body.contains("\"code\": 401")) {
                tokenStore.clear()
            }
        }
        return response
    }
}
