package com.example.adminscaffold.ui.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.example.adminscaffold.core.LocalContainer
import com.example.adminscaffold.core.TokenStore
import com.example.adminscaffold.data.AdminRepository
import com.example.adminscaffold.ui.common.FormField
import com.example.adminscaffold.ui.common.SmallLoading
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class LoginState(
    val loading: Boolean = false,
    val error: String? = null
)

class LoginViewModel(
    private val repo: AdminRepository,
    private val tokenStore: TokenStore
) : ViewModel() {
    private val _state = MutableStateFlow(LoginState())
    val state: StateFlow<LoginState> = _state.asStateFlow()

    fun login(username: String, password: String) {
        if (username.isBlank() || password.isBlank()) {
            _state.value = LoginState(error = "请输入用户名和密码")
            return
        }
        viewModelScope.launch {
            _state.value = LoginState(loading = true)
            runCatching { repo.login(username.trim(), password) }
                .onSuccess { token ->
                    tokenStore.save(token.accessToken)
                    _state.value = LoginState()
                }
                .onFailure { e ->
                    _state.value = LoginState(error = e.message ?: "登录失败")
                }
        }
    }

    fun consumeError() {
        _state.value = _state.value.copy(error = null)
    }
}

@Composable
fun LoginScreen() {
    val container = LocalContainer.current
    val vm: LoginViewModel = viewModel(
        factory = viewModelFactory {
            initializer { LoginViewModel(container.repository, container.tokenStore) }
        }
    )
    val state by vm.state.collectAsStateWithLifecycle()

    var username by remember { mutableStateOf("admin") }
    var password by remember { mutableStateOf("Admin@123") }

    Box(
        modifier = Modifier.fillMaxSize().padding(20.dp),
        contentAlignment = Alignment.Center
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            elevation = CardDefaults.cardElevation(defaultElevation = 8.dp)
        ) {
            Column(
                modifier = Modifier.padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Icon(
                    Icons.Default.Settings,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(40.dp)
                )
                Text("Admin Scaffold", style = MaterialTheme.typography.headlineSmall)
                Text(
                    "FastAPI + Compose 管理系统",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline
                )
                Spacer(Modifier.height(24.dp))

                FormField(username, { username = it }, "用户名")
                FormField(password, { password = it }, "密码", password = true)

                state.error?.let {
                    Text(
                        it,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }

                Spacer(Modifier.height(16.dp))
                Button(
                    onClick = { vm.login(username, password) },
                    enabled = !state.loading,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    if (state.loading) SmallLoading() else Text("登 录")
                }
                Spacer(Modifier.height(12.dp))
                Text(
                    "默认账号 admin / Admin@123，登录后请及时修改",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline
                )
            }
        }
    }
}
