package com.example.adminscaffold.ui.permissions

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
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
import com.example.adminscaffold.data.PermissionItem
import com.example.adminscaffold.ui.Perms
import com.example.adminscaffold.ui.common.ConfirmDialog
import com.example.adminscaffold.ui.common.EmptyState
import com.example.adminscaffold.ui.common.ErrorEffect
import com.example.adminscaffold.ui.common.FormField
import com.example.adminscaffold.ui.common.LoadingBar
import com.example.adminscaffold.ui.common.PagerBar
import com.example.adminscaffold.ui.common.SearchField

class PermissionViewModel(
    private val repo: AdminRepository
) : PagedViewModel<PermissionItem>(repo) {
    var module: String = ""
        private set

    override suspend fun fetch(page: Int, size: Int, keyword: String): Page<PermissionItem> =
        repo.permissions(page, size, keyword, module)

    fun searchWithModule(keyword: String, moduleValue: String) {
        module = moduleValue
        search(keyword)
    }
}

@Composable
fun PermissionScreen(repo: AdminRepository, perms: Perms) {
    val vm: PermissionViewModel = viewModel(
        factory = viewModelFactory { initializer { PermissionViewModel(repo) } }
    )
    val state by vm.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }

    var keywordInput by remember { mutableStateOf("") }
    var moduleInput by remember { mutableStateOf("") }
    var formTarget by remember { mutableStateOf<PermissionItem?>(null) }
    var formOpen by remember { mutableStateOf(false) }
    var deleteTarget by remember { mutableStateOf<PermissionItem?>(null) }

    LaunchedEffect(Unit) { vm.load(1) }
    ErrorEffect(state.error, vm::consumeError, snackbar)

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        floatingActionButton = {
            if (perms("permission:create")) {
                FloatingActionButton(onClick = {
                    formTarget = null
                    formOpen = true
                }) { Icon(Icons.Default.Add, contentDescription = "新增权限") }
            }
        }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            SearchField(
                value = keywordInput,
                onValueChange = { keywordInput = it },
                onSearch = { vm.searchWithModule(keywordInput, moduleInput) },
                placeholder = "权限编码 / 名称"
            )
            FormField(
                value = moduleInput,
                onValueChange = { moduleInput = it },
                label = "模块筛选（如 user，留空为全部）"
            )
            LoadingBar(state.loading)
            if (!state.loading && state.items.isEmpty()) EmptyState("暂无权限数据")
            LazyColumn(modifier = Modifier.weight(1f)) {
                items(state.items, key = { it.id }) { item ->
                    PermissionRow(
                        item = item,
                        perms = perms,
                        onEdit = { formTarget = item; formOpen = true },
                        onDelete = { deleteTarget = item }
                    )
                }
            }
            PagerBar(state, onPage = vm::goPage, onRefresh = vm::refresh)
        }
    }

    if (formOpen) {
        PermissionFormDialog(
            initial = formTarget,
            onDismiss = { formOpen = false },
            onSave = { body ->
                vm.runAction(
                    block = {
                        if (formTarget == null) repo.createPermission(body)
                        else repo.updatePermission(formTarget!!.id, body)
                    },
                    onSuccess = { formOpen = false }
                )
            }
        )
    }

    deleteTarget?.let { item ->
        ConfirmDialog(
            title = "删除权限",
            text = "确认删除权限「${item.code}」？角色上的该授权会一并解除。",
            onConfirm = {
                vm.runAction { repo.deletePermission(item.id) }
                deleteTarget = null
            },
            onDismiss = { deleteTarget = null }
        )
    }
}

@Composable
private fun PermissionRow(
    item: PermissionItem,
    perms: Perms,
    onEdit: () -> Unit,
    onDelete: () -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Column(Modifier.padding(12.dp)) {
            Text(item.code, style = MaterialTheme.typography.titleSmall)
            Text(
                "${item.name} · 模块 ${item.module} · 类型 ${item.kind} · 排序 ${item.sort}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline
            )
            Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                if (perms("permission:update")) TextButton(onClick = onEdit) { Text("编辑") }
                if (perms("permission:delete")) {
                    TextButton(onClick = onDelete) { Text("删除", color = MaterialTheme.colorScheme.error) }
                }
            }
        }
    }
}

@Composable
private fun PermissionFormDialog(
    initial: PermissionItem?,
    onDismiss: () -> Unit,
    onSave: (JsonBody) -> Unit
) {
    var code by remember(initial) { mutableStateOf(initial?.code ?: "") }
    var name by remember(initial) { mutableStateOf(initial?.name ?: "") }
    var module by remember(initial) { mutableStateOf(initial?.module ?: "system") }
    var kind by remember(initial) { mutableStateOf(initial?.kind ?: "api") }
    var sort by remember(initial) { mutableStateOf((initial?.sort ?: 0).toString()) }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial == null) "新增权限" else "编辑权限 · ${initial.code}") },
        text = {
            Column {
                FormField(code, { code = it }, "权限编码（如 report:export）", enabled = initial == null)
                FormField(name, { name = it }, "名称")
                FormField(module, { module = it }, "模块")
                Text("类型", style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(top = 6.dp))
                Row {
                    listOf("menu", "api", "button").forEach { option ->
                        FilterChip(
                            selected = kind == option,
                            onClick = { kind = option },
                            label = { Text(option) },
                            modifier = Modifier.padding(end = 6.dp)
                        )
                    }
                }
                FormField(sort, { sort = it }, "排序（数字）")
                error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall) }
            }
        },
        confirmButton = {
            Button(onClick = {
                if (code.isBlank() || name.isBlank()) {
                    error = "请填写权限编码与名称"
                    return@Button
                }
                val sortValue = sort.toIntOrNull() ?: 0
                val body: JsonBody = if (initial == null) {
                    mapOf(
                        "code" to code.trim(), "name" to name, "module" to module,
                        "kind" to kind, "sort" to sortValue
                    )
                } else {
                    mapOf("name" to name, "module" to module, "kind" to kind, "sort" to sortValue)
                }
                onSave(body)
            }) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}
