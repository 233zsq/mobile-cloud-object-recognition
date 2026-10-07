package com.mobilecloud.recognition.ui.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.mobilecloud.recognition.AppGraph
import com.mobilecloud.recognition.inference.ModelRepository
import kotlinx.coroutines.launch

data class SettingsUiState(
    val baseUrl: String = "",
    val token: String = "",
    val clientId: String = "",
    val modelInfo: ModelRepository.ModelInfo? = null,
    val modelError: String? = null,
    val saving: Boolean = false,
    val savedMessage: String? = null,
    val testing: Boolean = false,
    val testResult: String? = null,
)

/**
 * 设置页状态：服务器地址/令牌配置、连接测试、模型信息与重载（T04 验证入口）。
 */
class SettingsViewModel : ViewModel() {

    private val _state = mutableStateOf(SettingsUiState())
    val state: SettingsUiState get() = _state.value

    init {
        viewModelScope.launch {
            val baseUrl = AppGraph.settings.currentBaseUrl()
            val token = AppGraph.settings.currentToken()
            val clientId = AppGraph.settings.ensureClientId()
            update { it.copy(baseUrl = baseUrl, token = token, clientId = clientId) }
            AppGraph.apiClient.updateConfig(baseUrl, token)
            loadModelInfo()
        }
    }

    fun onBaseUrlChange(value: String) = update { it.copy(baseUrl = value) }
    fun onTokenChange(value: String) = update { it.copy(token = value) }

    fun save() {
        viewModelScope.launch {
            update { it.copy(saving = true) }
            AppGraph.settings.setBaseUrl(_state.value.baseUrl)
            AppGraph.settings.setToken(_state.value.token)
            val ok = AppGraph.apiClient.updateConfig(_state.value.baseUrl, _state.value.token)
            update {
                it.copy(
                    saving = false,
                    savedMessage = if (ok) "已保存并生效" else "地址格式无效（需 http(s)://host[:port]），未生效",
                )
            }
        }
    }

    fun testConnection() {
        viewModelScope.launch {
            update { it.copy(testing = true, testResult = null) }
            val result = try {
                val health = AppGraph.apiClient.api.health()
                "连接成功：HTTP ${health.status ?: "ok"}，模型已加载=${health.modelLoaded}"
            } catch (e: Exception) {
                "连接失败：${e.message ?: e.javaClass.simpleName}（确认服务地址、手机与服务器网络互通）"
            }
            update { it.copy(testing = false, testResult = result) }
        }
    }

    fun loadModelInfo() {
        viewModelScope.launch {
            val result = runCatching { AppGraph.modelRepository.info() }
            update { current ->
                result.fold(
                    onSuccess = { current.copy(modelInfo = it, modelError = null) },
                    onFailure = { current.copy(modelInfo = null, modelError = it.message ?: "模型加载失败") },
                )
            }
        }
    }

    fun reloadModel() {
        viewModelScope.launch {
            val result = runCatching { AppGraph.modelRepository.reload() }
            update { current ->
                result.fold(
                    onSuccess = { current.copy(modelInfo = it, modelError = null) },
                    onFailure = { current.copy(modelError = it.message ?: "模型加载失败") },
                )
            }
        }
    }

    fun consumeMessages() {
        update { it.copy(savedMessage = null, testResult = null) }
    }

    private fun update(transform: (SettingsUiState) -> SettingsUiState) {
        _state.value = transform(_state.value)
    }
}
