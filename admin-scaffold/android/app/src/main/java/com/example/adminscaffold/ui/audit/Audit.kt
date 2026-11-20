package com.example.adminscaffold.ui.audit

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
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
import com.example.adminscaffold.data.AuditItem
import com.example.adminscaffold.data.Page
import com.example.adminscaffold.ui.Perms
import com.example.adminscaffold.ui.common.EmptyState
import com.example.adminscaffold.ui.common.ErrorEffect
import com.example.adminscaffold.ui.common.LoadingBar
import com.example.adminscaffold.ui.common.PagerBar
import com.example.adminscaffold.ui.common.SearchField

private val ACTIONS = listOf(
    "" to "全部动作",
    "login" to "登录",
    "logout" to "退出",
    "create" to "新增",
    "update" to "编辑",
    "delete" to "删除"
)

class AuditViewModel(
    private val repo: AdminRepository
) : PagedViewModel<AuditItem>(repo) {
    var action: String = ""
        private set

    override suspend fun fetch(page: Int, size: Int, keyword: String): Page<AuditItem> =
        repo.auditLogs(page, size, keyword, action)

    fun searchWithAction(keyword: String, actionValue: String) {
        action = actionValue
        search(keyword)
    }
}

@Composable
fun AuditScreen(repo: AdminRepository, perms: Perms) {
    val vm: AuditViewModel = viewModel(
        factory = viewModelFactory { initializer { AuditViewModel(repo) } }
    )
    val state by vm.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }

    var keywordInput by remember { mutableStateOf("") }
    var action by remember { mutableStateOf("") }
    var expanded by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { vm.load(1) }
    ErrorEffect(state.error, vm::consumeError, snackbar)

    Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            SearchField(
                value = keywordInput,
                onValueChange = { keywordInput = it },
                onSearch = { vm.searchWithAction(keywordInput, action) },
                placeholder = "搜索详情 / 用户 / 资源"
            )
            Row(modifier = Modifier.padding(vertical = 4.dp)) {
                OutlinedButton(onClick = { expanded = true }) {
                    Text(ACTIONS.first { it.first == action }.second)
                }
                DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    ACTIONS.forEach { (value, label) ->
                        DropdownMenuItem(
                            text = { Text(label) },
                            onClick = {
                                action = value
                                expanded = false
                                vm.searchWithAction(keywordInput, value)
                            }
                        )
                    }
                }
                Text(
                    "数据来源：Elasticsearch",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.padding(start = 10.dp, top = 12.dp)
                )
            }
            LoadingBar(state.loading)
            if (!state.loading && state.items.isEmpty()) {
                EmptyState(
                    if (perms("audit:list"))
                        "暂无日志：请确认 Elasticsearch 已连接且已有写操作"
                    else "没有访问审计日志的权限"
                )
            }
            LazyColumn(modifier = Modifier.weight(1f)) {
                items(state.items) { item ->
                    AuditRow(item)
                }
            }
            PagerBar(state, onPage = vm::goPage, onRefresh = vm::refresh)
        }
    }
}

@Composable
private fun AuditRow(item: AuditItem) {
    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Column(Modifier.padding(12.dp)) {
            Row {
                AssistChip(onClick = {}, label = { Text(item.action) }, enabled = false)
                Text(
                    item.username,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(start = 8.dp, top = 8.dp)
                )
                Text(
                    item.resource,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.padding(start = 8.dp, top = 8.dp)
                )
            }
            Text(item.detail, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp))
            Text(
                "${item.ts.replace('T', ' ').take(19)} · ${item.ip}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline
            )
        }
    }
}
