package com.example.adminscaffold.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.adminscaffold.core.AppContainer
import com.example.adminscaffold.ui.auth.LoginScreen
import com.example.adminscaffold.ui.main.MainScreen

@Composable
fun AppRoot(container: AppContainer) {
    val token by container.tokenStore.token.collectAsStateWithLifecycle()
    if (token.isNullOrBlank()) {
        LoginScreen()
    } else {
        MainScreen()
    }
}
