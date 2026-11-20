package com.example.adminscaffold.ui.common

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.example.adminscaffold.core.PagedUiState

@Composable
fun ErrorEffect(
    message: String?,
    onConsume: () -> Unit,
    snackbar: SnackbarHostState
) {
    LaunchedEffect(message) {
        if (!message.isNullOrBlank()) {
            snackbar.showSnackbar(message)
            onConsume()
        }
    }
}

@Composable
fun SearchField(
    value: String,
    onValueChange: (String) -> Unit,
    onSearch: () -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier
) {
    Row(modifier = modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            placeholder = { Text(placeholder) },
            singleLine = true,
            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
            modifier = Modifier.weight(1f)
        )
        Spacer(Modifier.width(8.dp))
        Button(onClick = onSearch) { Text("搜索") }
    }
}

@Composable
fun LoadingBar(loading: Boolean) {
    if (loading) {
        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
    } else {
        Spacer(Modifier.height(4.dp))
    }
}

@Composable
fun EmptyState(text: String) {
    Box(
        modifier = Modifier.fillMaxWidth().padding(32.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(text, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun PagerBar(
    state: PagedUiState<*>,
    onPage: (Int) -> Unit,
    onRefresh: () -> Unit
) {
    val maxPage = ((state.total + state.size - 1) / state.size).coerceAtLeast(1)
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            "共 ${state.total} 条 · 第 ${state.page}/$maxPage 页",
            style = MaterialTheme.typography.bodySmall
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onRefresh) {
                Icon(Icons.Default.Refresh, contentDescription = "刷新")
            }
            IconButton(onClick = { onPage(state.page - 1) }, enabled = state.page > 1) {
                Icon(Icons.Default.ChevronLeft, contentDescription = "上一页")
            }
            IconButton(onClick = { onPage(state.page + 1) }, enabled = state.page < maxPage) {
                Icon(Icons.Default.ChevronRight, contentDescription = "下一页")
            }
        }
    }
}

@Composable
fun ConfirmDialog(
    title: String,
    text: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = { Button(onClick = onConfirm) { Text("确定") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}

@Composable
fun FormField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    enabled: Boolean = true,
    password: Boolean = false,
    modifier: Modifier = Modifier
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        enabled = enabled,
        singleLine = true,
        visualTransformation = if (password) PasswordVisualTransformation()
        else androidx.compose.ui.text.input.VisualTransformation.None,
        modifier = modifier.fillMaxWidth().padding(vertical = 4.dp)
    )
}

@Composable
fun SmallLoading() {
    CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
}

@Composable
fun KeyValueLine(label: String, value: String) {
    Column(modifier = Modifier.padding(vertical = 4.dp)) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}
