package com.example.adminscaffold.ui

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Circle
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Person
import androidx.compose.ui.graphics.vector.ImageVector
import com.example.adminscaffold.data.Menu

object Routes {
    const val DASHBOARD = "dashboard"
    const val USERS = "system_user"
    const val ROLES = "system_role"
    const val PERMISSIONS = "system_permission"
    const val AUDIT = "system_audit"

    val all = listOf(DASHBOARD, USERS, ROLES, PERMISSIONS, AUDIT)
}

/** 后端 path 形如 /system/user -> Compose route（route 中不能出现 '/'） */
fun Menu.toRoute(): String = path.trimStart('/').replace('/', "_")

/** 后端下发的是 Element Plus 图标名，这里映射到 Material Icons */
fun menuIcon(name: String): ImageVector = when (name) {
    "DataBoard" -> Icons.Default.Home
    "User" -> Icons.Default.Person
    "UserFilled" -> Icons.Default.Groups
    "Lock" -> Icons.Default.Lock
    "Document" -> Icons.Default.Description
    else -> Icons.Default.Circle
}

/** 按钮级权限判定：与 Vue3 的 hasPerm / 后端 require_perm 口径一致 */
data class Perms(
    val codes: Set<String> = emptySet(),
    val isSuperuser: Boolean = false
) {
    operator fun invoke(code: String): Boolean = isSuperuser || code in codes
}
