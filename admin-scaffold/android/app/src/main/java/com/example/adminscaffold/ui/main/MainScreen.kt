package com.example.adminscaffold.ui.main

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExitToApp
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.example.adminscaffold.core.LocalContainer
import com.example.adminscaffold.ui.Perms
import com.example.adminscaffold.ui.Routes
import com.example.adminscaffold.ui.common.ErrorEffect
import com.example.adminscaffold.ui.dashboard.DashboardScreen
import com.example.adminscaffold.ui.menuIcon
import com.example.adminscaffold.ui.permissions.PermissionScreen
import com.example.adminscaffold.ui.roles.RoleScreen
import com.example.adminscaffold.ui.toRoute
import com.example.adminscaffold.ui.users.UserScreen
import com.example.adminscaffold.ui.audit.AuditScreen
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen() {
    val container = LocalContainer.current
    val vm: MainViewModel = viewModel(
        factory = viewModelFactory { initializer { MainViewModel(container.repository) } }
    )
    val state by vm.state.collectAsStateWithLifecycle()

    val navController = rememberNavController()
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }

    val backStack by navController.currentBackStackEntryAsState()
    val currentRoute = backStack?.destination?.route
    val title = state.menus.firstOrNull { it.toRoute() == currentRoute }?.title ?: "工作台"

    val perms = Perms(
        codes = state.profile?.permissions?.toSet() ?: emptySet(),
        isSuperuser = state.profile?.isSuperuser == true
    )

    // 后端按权限下发菜单；若没有工作台权限，自动跳到第一个可用页面
    LaunchedEffect(state.menus) {
        if (state.menus.isNotEmpty() && state.menus.none { it.toRoute() == Routes.DASHBOARD }) {
            navController.navigate(state.menus.first().toRoute()) {
                popUpTo(Routes.DASHBOARD) { inclusive = true }
                launchSingleTop = true
            }
        }
    }
    ErrorEffect(state.error, onConsume = { /* 保留错误提示，可下拉刷新重载 */ }, snackbar = snackbar)

    fun logout() {
        scope.launch {
            runCatching { container.repository.logout() }
            container.tokenStore.clear()
        }
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Admin Scaffold", style = MaterialTheme.typography.titleMedium)
                    Text(
                        state.profile?.nickname?.takeIf { it.isNotBlank() }
                            ?: state.profile?.username ?: "未登录",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.outline
                    )
                }
                Spacer(Modifier.height(8.dp))
                state.menus.forEach { menu ->
                    val route = menu.toRoute()
                    NavigationDrawerItem(
                        label = { Text(menu.title) },
                        icon = { Icon(menuIcon(menu.icon), contentDescription = null) },
                        selected = currentRoute == route,
                        onClick = {
                            navController.navigate(route) { launchSingleTop = true }
                            scope.launch { drawerState.close() }
                        },
                        modifier = Modifier.padding(horizontal = 12.dp)
                    )
                }
            }
        }
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text(title) },
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawerState.open() } }) {
                            Icon(Icons.Default.Menu, contentDescription = "菜单")
                        }
                    },
                    actions = {
                        IconButton(onClick = ::logout) {
                            Icon(Icons.Default.ExitToApp, contentDescription = "退出登录")
                        }
                    }
                )
            },
            snackbarHost = { SnackbarHost(snackbar) }
        ) { padding ->
            NavHost(
                navController = navController,
                startDestination = Routes.DASHBOARD,
                modifier = Modifier.fillMaxSize().padding(padding)
            ) {
                composable(Routes.DASHBOARD) {
                    DashboardScreen(container.repository, state.profile, perms)
                }
                composable(Routes.USERS) {
                    UserScreen(container.repository, perms)
                }
                composable(Routes.ROLES) {
                    RoleScreen(container.repository, perms)
                }
                composable(Routes.PERMISSIONS) {
                    PermissionScreen(container.repository, perms)
                }
                composable(Routes.AUDIT) {
                    AuditScreen(container.repository, perms)
                }
            }
        }
    }
}
