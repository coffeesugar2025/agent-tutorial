package com.example.adminscaffold.core

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.adminscaffold.data.AdminRepository
import com.example.adminscaffold.data.Page
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PagedUiState<T>(
    val items: List<T> = emptyList(),
    val total: Int = 0,
    val page: Int = 1,
    val size: Int = 10,
    val keyword: String = "",
    val loading: Boolean = false,
    val error: String? = null
)

/** 四个列表页共用的分页 / 搜索 / 刷新 / 写操作后重载逻辑 */
abstract class PagedViewModel<T>(protected val repo: AdminRepository) : ViewModel() {
    private val _state = MutableStateFlow(PagedUiState<T>())
    val state: StateFlow<PagedUiState<T>> = _state.asStateFlow()

    protected abstract suspend fun fetch(page: Int, size: Int, keyword: String): Page<T>

    fun load(
        page: Int = _state.value.page,
        keyword: String = _state.value.keyword
    ) {
        viewModelScope.launch {
            val size = _state.value.size
            _state.update {
                it.copy(loading = true, error = null, page = page, keyword = keyword)
            }
            runCatching { fetch(page, size, keyword) }
                .onSuccess { result ->
                    _state.update {
                        it.copy(
                            loading = false,
                            items = result.items,
                            total = result.total,
                            page = result.page
                        )
                    }
                }
                .onFailure { e ->
                    _state.update {
                        it.copy(loading = false, error = e.message ?: "加载失败")
                    }
                }
        }
    }

    fun search(keyword: String) = load(page = 1, keyword = keyword)
    fun goPage(page: Int) = load(page = page)
    fun refresh() = load()
    fun consumeError() = _state.update { it.copy(error = null) }

    /** 新增/编辑/删除：成功自动重载当前页，失败把错误交给 ErrorEffect 弹 Snackbar */
    fun runAction(block: suspend () -> Unit, onSuccess: () -> Unit = {}) {
        viewModelScope.launch {
            runCatching { block() }
                .onSuccess {
                    onSuccess()
                    load(page = _state.value.page)
                }
                .onFailure { e ->
                    _state.update { it.copy(error = e.message ?: "操作失败") }
                }
        }
    }
}
