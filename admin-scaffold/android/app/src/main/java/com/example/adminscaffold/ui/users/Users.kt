package com.example.adminscaffold.ui.users

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.example.adminscaffold.core.LocalContainer
import com.example.adminscaffold.core.PagedViewModel
import com.example.adminscaffold.data.AdminRepository
import com.example.adminscaffold.data.JsonBody
import com.example.adminscaffold.data.Page
import com.example.adminscaffold.data.RoleOption
import com.example.adminscaffold.data.UserItem
import com.example.adminscaffold.ui.Perms
import com.example.adminscaffold.ui.common.ConfirmDialog
import com.example.adminscaffold.ui.common.EmptyState
import com.example.adminscaffold.ui.common.ErrorEffect
import com.example.adminscaffold.ui.common.FormField
import com.example.adminscaffold.ui.common.LoadingBar
import com.example.adminscaffold.ui.common.PagerBar
import com.example.adminscaffold.ui.common.SearchField

class UserViewModel(repo: AdminRepository) : PagedViewModel<UserItem>(repo) {
    override suspend fun fetch(page: Int, size: Int, keyword: String): Page<UserItem> =
        repo.users(page, size, keyword)
}

@Composable
fun UserScreen(repo: AdminRepository, perms: Perms) {
    val vm: UserViewModel = viewModel(
        factory = viewModelFactory { initializer { UserViewModel(repo) } }
    )
    val state by vm.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }

    var formTarget by remember { mutableStateOf<UserItem?>(null) }
    var formOpen by remember { mutableStateOf(false) }
    var deleteTarget by remember { mutableStateOf<UserItem?>(null) }
    var resetTarget by remember { mutableStateOf<UserItem?>(null) }
    var roleOptions by remember { mutableStateOf<List<RoleOption>>(emptyList()) }
    var keywordInput by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        vm.load(1)
        roleOptions = runCatching { repo.roleOptions() }.getOrDefault(emptyList())
    }
    ErrorEffect(state.error, vm::consumeError, snackbar)

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        floatingActionButton = {
            if (perms("user:create")) {
                FloatingActionButton(onClick = {
                    formTarget = null
                    formOpen = true
                }) { Icon(Icons.Default.Add, contentDescription = "新增用户") }
            }
        }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            SearchField(
                value = keywordInput,
                onValueChange = { keywordInput = it },
                onSearch = { vm.search(keywordInput) },
                placeholder = "用户名 / 昵称 / 邮箱"
            )
            LoadingBar(state.loading)
            if (!state.loading && state.items.isEmpty()) {
                EmptyState("暂无用户数据")
            }
            LazyColumn(modifier = Modifier.weight(1f)) {
                items(state.items, key = { it.id }) { user ->
                    UserRow(
                        user = user,
                        perms = perms,
                        onEdit = { formTarget = user; formOpen = true },
                        onReset = { resetTarget = user },
                        onDelete = { deleteTarget = user }
                    )
                }
            }
            PagerBar(state, onPage = vm::goPage, onRefresh = vm::refresh)
        }
    }

    if (formOpen) {
        UserFormDialog(
            initial = formTarget,
            roleOptions = roleOptions,
            onDismiss = { formOpen = false },
            onSave = { body ->
                vm.runAction(
                    block = {
                        if (formTarget == null) repo.createUser(body)
                        else repo.updateUser(formTarget!!.id, body)
                    },
                    onSuccess = { formOpen = false }
                )
            }
        )
    }

    deleteTarget?.let { user ->
        ConfirmDialog(
            title = "删除用户",
            text = "确认删除用户「${user.username}」？该操作不可撤销。",
            onConfirm = {
                vm.runAction { repo.deleteUser(user.id) }
                deleteTarget = null
            },
            onDismiss = { deleteTarget = null }
        )
    }

    resetTarget?.let { user ->
        ResetPasswordDialog(
            username = user.username,
            onDismiss = { resetTarget = null },
            onSave = { password ->
                vm.runAction(
                    block = { repo.resetPassword(user.id, password) },
                    onSuccess = { resetTarget = null }
                )
            }
        )
    }
}

@Composable
private fun UserRow(
    user: UserItem,
    perms: Perms,
    onEdit: () -> Unit,
    onReset: () -> Unit,
    onDelete: () -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(user.username, style = MaterialTheme.typography.titleSmall)
                Text(
                    if (user.isActive) "启用" else "禁用",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (user.isActive) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(start = 8.dp)
                )
                if (user.isSuperuser) {
                    Text(
                        "超管",
                        style = MaterialTheme.typography.labelSmall,
                        modifier = Modifier.padding(start = 6.dp)
                    )
                }
            }
            Text(
                "${user.nickname.ifBlank { "-" }} · ${user.email.ifBlank { "-" }} · ${user.phone.ifBlank { "-" }}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline
            )
            Text(
                "角色：${user.roles.joinToString("、").ifBlank { "-" }}",
                style = MaterialTheme.typography.bodySmall
            )
            Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                if (perms("user:update")) {
                    TextButton(onClick = onEdit) { Text("编辑") }
                    TextButton(onClick = onReset) { Text("重置密码") }
                }
                if (perms("user:delete")) {
                    TextButton(onClick = onDelete) { Text("删除", color = MaterialTheme.colorScheme.error) }
                }
            }
        }
    }
}

@Composable
private fun UserFormDialog(
    initial: UserItem?,
    roleOptions: List<RoleOption>,
    onDismiss: () -> Unit,
    onSave: (JsonBody) -> Unit
) {
    var username by remember(initial) { mutableStateOf(initial?.username ?: "") }
    var password by remember(initial) { mutableStateOf("") }
    var nickname by remember(initial) { mutableStateOf(initial?.nickname ?: "") }
    var email by remember(initial) { mutableStateOf(initial?.email ?: "") }
    var phone by remember(initial) { mutableStateOf(initial?.phone ?: "") }
    var active by remember(initial) { mutableStateOf(initial?.isActive ?: true) }
    var selectedRoles by remember(initial) {
        mutableStateOf(initial?.roleIds ?: emptyList())
    }
    var localError by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "新增用户" else "编辑用户 · ${initial.username}") },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 460.dp)
                    .verticalScroll(rememberScrollState())
            ) {
                FormField(username, { username = it }, "用户名", enabled = initial == null)
                if (initial == null) {
                    FormField(password, { password = it }, "初始密码（至少 6 位）", password = true)
                }
                FormField(nickname, { nickname = it }, "昵称")
                FormField(email, { email = it }, "邮箱")
                FormField(phone, { phone = it }, "手机号")

                Text("角色", style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(top = 8.dp))
                Column(modifier = Modifier.fillMaxWidth().heightIn(max = 130.dp).verticalScroll(rememberScrollState())) {
                    roleOptions.forEach { role ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(
                                checked = role.id in selectedRoles,
                                onCheckedChange = { checked ->
                                    selectedRoles = if (checked) selectedRoles + role.id
                                    else selectedRoles - role.id
                                }
                            )
                            Text("${role.name} (${role.code})", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    if (roleOptions.isEmpty()) {
                        Text("暂无可选角色", style = MaterialTheme.typography.labelSmall)
                    }
                }

                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("启用", style = MaterialTheme.typography.bodySmall)
                    Switch(checked = active, onCheckedChange = { active = it }, modifier = Modifier.padding(start = 8.dp))
                }

                localError?.let {
                    Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall)
                }
            }
        },
        confirmButton = {
            Button(onClick = {
                if (username.isBlank() || (initial == null && password.length < 6)) {
                    localError = "请填写用户名；新增时密码至少 6 位"
                    return@Button
                }
                localError = null
                val body: JsonBody = if (initial == null) {
                    mapOf(
                        "username" to username.trim(),
                        "password" to password,
                        "nickname" to nickname,
                        "email" to email,
                        "phone" to phone,
                        "is_active" to active,
                        "role_ids" to selectedRoles
                    )
                } else {
                    mapOf(
                        "nickname" to nickname,
                        "email" to email,
                        "phone" to phone,
                        "is_active" to active,
                        "role_ids" to selectedRoles
                    )
                }
                onSave(body)
            }) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}

@Composable
private fun ResetPasswordDialog(
    username: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit
) {
    var password by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("重置密码 · $username") },
        text = {
            Column {
                FormField(password, { password = it }, "新密码（至少 6 位）", password = true)
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            Button(onClick = {
                if (password.length < 6) {
                    error = "密码至少 6 位"
                } else {
                    onSave(password)
                }
            }) { Text("确定") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}
