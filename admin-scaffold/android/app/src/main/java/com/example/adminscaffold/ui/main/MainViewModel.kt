package com.example.adminscaffold.ui.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.adminscaffold.data.AdminRepository
import com.example.adminscaffold.data.Menu
import com.example.adminscaffold.data.Profile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class MainState(
    val profile: Profile? = null,
    val menus: List<Menu> = emptyList(),
    val loading: Boolean = true,
    val error: String? = null
)

class MainViewModel(private val repo: AdminRepository) : ViewModel() {
    private val _state = MutableStateFlow(MainState())
    val state: StateFlow<MainState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, error = null)
            runCatching {
                val profile = repo.me()
                val menus = repo.menus()
                profile to menus
            }.onSuccess { (profile, menus) ->
                _state.value = MainState(profile = profile, menus = menus, loading = false)
            }.onFailure { e ->
                _state.value = MainState(loading = false, error = e.message ?: "加载菜单失败")
            }
        }
    }
}
