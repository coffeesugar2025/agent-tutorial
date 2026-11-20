package com.example.adminscaffold.ui.dashboard

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.example.adminscaffold.data.AdminRepository
import com.example.adminscaffold.data.HealthState
import com.example.adminscaffold.data.Profile
import com.example.adminscaffold.ui.Perms
import com.example.adminscaffold.ui.common.KeyValueLine

@Composable
fun DashboardScreen(
    repo: AdminRepository,
    profile: Profile?,
    perms: Perms
) {
    var health by remember { mutableStateOf<HealthState?>(null) }

    LaunchedEffect(Unit) {
        health = runCatching { repo.health() }.getOrNull()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                Text(
                    "欢迎回来，${profile?.nickname?.takeIf { it.isNotBlank() } ?: profile?.username ?: "用户"}",
                    style = MaterialTheme.typography.titleMedium
                )
                KeyValueLine("角色", profile?.roles?.joinToString("、").orEmpty().ifBlank { "-" })
                KeyValueLine("已授予权限", "${profile?.permissions?.size ?: 0} 项")
                KeyValueLine("超级管理员", if (profile?.isSuperuser == true) "是" else "否")
            }
        }

        Card(modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) {
            Column(Modifier.padding(16.dp)) {
                Text("中间件连通状态", style = MaterialTheme.typography.titleSmall)
                health?.entries()?.forEach { (label, online) ->
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        AssistChip(
                            onClick = {},
                            label = { Text(if (online) "在线" else "离线") },
                            enabled = false
                        )
                        Text(label, modifier = Modifier.padding(start = 12.dp))
                    }
                } ?: Text(
                    "正在检测…",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline
                )
                Text(
                    "除 MySQL 外组件离线时服务自动降级，登录与 CRUD 不受影响。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.outline,
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
        }

        Card(modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) {
            Column(Modifier.padding(16.dp)) {
                Text("脚手架能力", style = MaterialTheme.typography.titleSmall)
                listOf(
                    "JWT + Redis 黑名单", "RBAC 三级权限", "接口级 require_perm",
                    "按钮级权限控制", "ES 审计检索", "RabbitMQ 事件",
                    "Kafka 消息流", "统一分页 CRUD"
                ).chunked(2).forEach { row ->
                    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                        row.forEach { text ->
                            AssistChip(
                                onClick = {},
                                label = { Text(text, style = MaterialTheme.typography.labelSmall) },
                                modifier = Modifier.padding(end = 8.dp)
                            )
                        }
                    }
                }
            }
        }

        if (!perms("dashboard:view")) {
            Text(
                "当前账号没有工作台查看权限，请联系管理员。",
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = 12.dp)
            )
        }
    }
}
