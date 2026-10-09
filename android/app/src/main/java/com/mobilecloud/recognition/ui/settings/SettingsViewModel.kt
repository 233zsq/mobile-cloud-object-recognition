package com.mobilecloud.recognition.ui.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.mobilecloud.recognition.AppGraph
import com.mobilecloud.recognition.data.remote.BaseUrl
import com.mobilecloud.recognition.data.settings.SettingsStore
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
    val examplesAvailable: Boolean = false,
    val checkRunning: Boolean = false,
    val checkProgress: String? = null,
    val checkSummary: String? = null,
    val checkFailed: Boolean = false,
    val checkZipPath: String? = null,
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
            update { it.copy(examplesAvailable = AppGraph.consistencyCheck.hasExamples()) }
            loadModelInfo()
        }
    }

    fun onBaseUrlChange(value: String) = update { it.copy(baseUrl = value) }
    fun onTokenChange(value: String) = update { it.copy(token = value) }

    /** 保存：先校验地址格式，无效则完全不改动持久化配置（避免把不可用地址写坏） */
    fun save() {
        val url = _state.value.baseUrl.trim()
        val token = _state.value.token.trim()
        if (url != SettingsStore.DEFAULT_BASE_URL && !BaseUrl.isValid(url)) {
            update {
                it.copy(
                    savedMessage = "地址格式无效（需 http(s)://主机[:端口]），未保存；此前配置保持不变",
                )
            }
            return
        }
        viewModelScope.launch {
            update { it.copy(saving = true) }
            AppGraph.settings.setBaseUrl(url)
            AppGraph.settings.setToken(token)
            val ok = AppGraph.apiClient.updateConfig(url, token)
            update {
                it.copy(
                    saving = false,
                    savedMessage = if (ok) "已保存并生效" else "地址无效，未生效（原配置保持不变）",
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

    /** 端云同图一致性自检：20 张交接样例跑参考张量与图片链路两种模式（T05/M02–M04） */
    fun runConsistencyCheck() {
        if (_state.value.checkRunning) return
        update {
            it.copy(
                checkRunning = true,
                checkProgress = "准备中…",
                checkSummary = null,
                checkFailed = false,
                checkZipPath = null,
            )
        }
        viewModelScope.launch {
            try {
                val summary = AppGraph.modelRepository.withBundle { bundle ->
                    AppGraph.consistencyCheck.run(bundle) { progress ->
                        update { it.copy(checkProgress = progress) }
                    }
                }
                update {
                    it.copy(
                        checkRunning = false,
                        checkProgress = null,
                        checkFailed = !summary.allPassed,
                        checkZipPath = summary.zipFile.absolutePath,
                        checkSummary = buildString {
                            appendLine("run_id：${summary.runId}")
                            appendLine("设备：${summary.device}")
                            appendLine("运行时：${summary.runtime}")
                            appendLine("参考张量模式：${summary.reference.passed}/${summary.reference.total} 通过")
                            appendLine("图片链路模式：${summary.imageChain.passed}/${summary.imageChain.total} 通过")
                            val failures = summary.reference.failures + summary.imageChain.failures
                            if (failures.isNotEmpty()) {
                                appendLine("未通过样例：")
                                failures.take(8).forEach { appendLine(" · $it") }
                            }
                            appendLine("输出目录：${summary.outputDir.absolutePath}")
                        },
                    )
                }
            } catch (e: Exception) {
                update {
                    it.copy(
                        checkRunning = false,
                        checkProgress = null,
                        checkFailed = true,
                        checkSummary = "自检失败：${e.message ?: e.javaClass.simpleName}",
                    )
                }
            }
        }
    }

    private fun update(transform: (SettingsUiState) -> SettingsUiState) {
        _state.value = transform(_state.value)
    }
}
