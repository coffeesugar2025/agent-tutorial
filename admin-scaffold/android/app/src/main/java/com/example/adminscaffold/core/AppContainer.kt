package com.example.adminscaffold.core

import android.content.Context
import androidx.compose.runtime.staticCompositionLocalOf
import com.example.adminscaffold.BuildConfig
import com.example.adminscaffold.data.AdminApi
import com.example.adminscaffold.data.AdminRepository
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

/** 轻量手动 DI；如需 Hilt，把这里换成 @Module 即可，上层 UI 不用改。 */
class AppContainer(context: Context) {
    val tokenStore = TokenStore(context)

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .addInterceptor(AuthInterceptor(tokenStore))
        .addInterceptor(UnauthorizedInterceptor(tokenStore))
        .addInterceptor(
            HttpLoggingInterceptor().apply {
                level = if (BuildConfig.DEBUG) HttpLoggingInterceptor.Level.BODY
                else HttpLoggingInterceptor.Level.NONE
            }
        )
        .build()

    private val retrofit = Retrofit.Builder()
        .baseUrl(BuildConfig.API_BASE_URL)
        .client(client)
        .addConverterFactory(GsonConverterFactory.create())
        .build()

    val api: AdminApi = retrofit.create(AdminApi::class.java)
    val repository = AdminRepository(api, tokenStore)
}

val LocalContainer = staticCompositionLocalOf<AppContainer> {
    error("AppContainer 未通过 CompositionLocalProvider 提供")
}
