package com.example.adminscaffold.core

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * access token 本地持久化。StateFlow 让 AppRoot 在登录 / 退出 / 401 时自动切换页面。
 * 脚手架用 SharedPreferences；生产建议改用 EncryptedSharedPreferences。
 */
class TokenStore(context: Context) {
    private val prefs = context.applicationContext
        .getSharedPreferences("admin_auth", Context.MODE_PRIVATE)

    private val _token = MutableStateFlow(prefs.getString(KEY_TOKEN, null))
    val token: StateFlow<String?> = _token.asStateFlow()

    fun current(): String? = _token.value

    fun save(token: String) {
        prefs.edit().putString(KEY_TOKEN, token).apply()
        _token.value = token
    }

    fun clear() {
        prefs.edit().remove(KEY_TOKEN).apply()
        _token.value = null
    }

    private companion object {
        const val KEY_TOKEN = "access_token"
    }
}
