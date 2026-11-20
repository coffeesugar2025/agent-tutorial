package com.example.adminscaffold.ui.roles

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
import com.example.adminscaffold.core.PagedViewModel
import com.example.adminscaffold.data.AdminRepository
import com.example.adminscaffold.data.JsonBody
import com.example.adminscaffold.data.Page
import com.example.adminscaffold.data.PermGroup
import com.example.adminscaffold.data.RoleItem
import com.example.adminscaffold.ui.Perms
import com.example.adminscaffold.ui.common.ConfirmDialog
import com.example.adminscaffold.ui.common.EmptyState
import com.example.adminscaffold.ui.common.ErrorEffect
import com.example.adminscaffold.ui.common.FormField
import com.example.adminscaffold.ui.common.LoadingBar
import com.example.adminscaffold.ui.common.PagerBar
import com.example.adminscaffold.ui.common.SearchField

class RoleViewModel(repo: AdminRepository) : PagedViewModel<RoleItem>(repo) {
    override suspend fun fetch(page: Int, size: Int, keyword: String): Page<RoleItem> =
        repo.roles(page, size, keyword)
}

@Composable
fun RoleScreen(repo: AdminRepository, perms: Perms) {
    val vm: RoleViewModel = viewModel(
        factory = viewModelFactory { initializer { RoleViewModel(repo) } }
    )
    val state by vm.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }

    var keywordInput by remember { mutableStateOf("") }
    var formTarget by remember { mutableStateOf<RoleItem?>(null) }
    var formOpen by remember { mutableStateOf(false) }
    var deleteTarget by remember { mutableStateOf<RoleItem?>(null) }
    var assignTarget by remember { mutableStateOf<RoleItem?>(null) }
    var groups by remember { mutableStateOf<List<PermGroup>>(emptyList()) }

    LaunchedEffect(Unit) { vm.load(1) }
    LaunchedEffect(assignTarget) {
        if (assignTarget != null) {
            groups = runCatching { repo.permissionTree() }.getOrDefault(emptyList())
        }
    }
    ErrorEffect(state.error, vm::consumeError, snackbar)

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        floatingActionButton = {
            if (perms("role:create")) {
                FloatingActionButton(onClick = {
                    formTarget = null
                    formOpen = true
                }) { Icon(Icons.Default.Add, contentDescription = "新增角色") }
            }
        }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            SearchField(
                value = keywordInput,
                onValueChange = { keywordInput = it },
                onSearch = { vm.search(keywordInput) },
                placeholder = "角色编码 / 名称"
            )
            LoadingBar(state.loading)
            if (!state.loading && state.items.isEmpty()) EmptyState("暂无角色数据")
            LazyColumn(modifier = Modifier.weight(1f)) {
                items(state.items, key = { it.id }) { role ->
                    RoleRow(
                        role = role,
                        perms = perms,
                        onEdit = { formTarget = role; formOpen = true },
                        onAssign = { assignTarget = role },
                        onDelete = { deleteTarget = role }
                    )
                }
            }
            PagerBar(state, onPage = vm::goPage, onRefresh = vm::refresh)
        }
    }

    if (formOpen) {
        RoleFormDialog(
            initial = formTarget,
            onDismiss = { formOpen = false },
            onSave = { body ->
                vm.runAction(
                    block = {
                        if (formTarget == null) repo.createRole(body)
                        else repo.updateRole(formTarget!!.id, body)
                    },
                    onSuccess = { formOpen = false }
                )
            }
        )
    }

    deleteTarget?.let { role ->
        ConfirmDialog(
            title = "删除角色",
            text = "确认删除角色「${role.name}」？关联用户的授权会一并解除。",
            onConfirm = {
                vm.runAction { repo.deleteRole(role.id) }
                deleteTarget = null
            },
            onDismiss = { deleteTarget = null }
        )
    }

    assignTarget?.let { role ->
        PermissionAssignDialog(
            role = role,
            groups = groups,
            onDismiss = { assignTarget = null },
            onSave = { ids ->
                vm.runAction(
                    block = { repo.assignPermissions(role.id, ids) },
                    onSuccess = { assignTarget = null }
                )
            }
        )
    }
}

@Composable
private fun RoleRow(
    role: RoleItem,
    perms: Perms,
    onEdit: () -> Unit,
    onAssign: () -> Unit,
    onDelete: () -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(role.name, style = MaterialTheme.typography.titleSmall)
                Text(
                    role.code,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.padding(start = 8.dp)
                )
                Text(
                    if (role.isActive) "启用" else "禁用",
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier.padding(start = 8.dp)
                )
            }
            Text(
                role.description.ifBlank { "无描述" },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline
            )
            Text("已分配 ${role.permissionIds.size} 项权限", style = MaterialTheme.typography.bodySmall)
            Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                if (perms("role:update")) {
                    TextButton(onClick = onEdit) { Text("编辑") }
                    TextButton(onClick = onAssign) { Text("分配权限") }
                }
                if (perms("role:delete")) {
                    TextButton(onClick = onDelete) { Text("删除", color = MaterialTheme.colorScheme.error) }
                }
            }
        }
    }
}

@Composable
private fun RoleFormDialog(
    initial: RoleItem?,
    onDismiss: () -> Unit,
    onSave: (JsonBody) -> Unit
) {
    var code by remember(initial) { mutableStateOf(initial?.code ?: "") }
    var name by remember(initial) { mutableStateOf(initial?.name ?: "") }
    var description by remember(initial) { mutableStateOf(initial?.description ?: "") }
    var active by remember(initial) { mutableStateOf(initial?.isActive ?: true) }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "新增角色" else "编辑角色 · ${initial.code}") },
        text = {
            Column {
                FormField(code, { code = it }, "角色编码（如 ops_admin）", enabled = initial == null)
                FormField(name, { name = it }, "角色名称")
                FormField(description, { description = it }, "描述")
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("启用", style = MaterialTheme.typography.bodySmall)
                    Switch(checked = active, onCheckedChange = { active = it }, modifier = Modifier.padding(start = 8.dp))
                }
                error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall) }
            }
        },
        confirmButton = {
            Button(onClick = {
                if (code.isBlank() || name.isBlank()) {
                    error = "请填写角色编码与名称"
                    return@Button
                }
                val body: JsonBody = if (initial == null) {
                    mapOf(
                        "code" to code.trim(), "name" to name,
                        "description" to description, "is_active" to active,
                        "permission_ids" to emptyList<Int>()
                    )
                } else {
                    mapOf("name" to name, "description" to description, "is_active" to active)
                }
                onSave(body)
            }) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}

@Composable
private fun PermissionAssignDialog(
    role: RoleItem,
    groups: List<PermGroup>,
    onDismiss: () -> Unit,
    onSave: (List<Int>) -> Unit
) {
    var checked by remember(role.id) { mutableStateOf(role.permissionIds.toSet()) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("分配权限 · ${role.code}") },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 420.dp)
                    .verticalScroll(rememberScrollState())
            ) {
                if (groups.isEmpty()) {
                    Text("权限列表加载中或暂无数据", style = MaterialTheme.typography.bodySmall)
                }
                groups.forEach { group ->
                    Text(
                        group.module,
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                    group.children.forEach { child ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(
                                checked = child.id in checked,
                                onCheckedChange = { selected ->
                                    checked = if (selected) checked + child.id else checked - child.id
                                }
                            )
                            Column {
                                Text(child.name, style = MaterialTheme.typography.bodySmall)
                                Text(
                                    child.code,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.outline
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { Button(onClick = { onSave(checked.toList()) }) { Text("保存分配") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}
